"""Unit tests for TavilyEnricher, IntelCache, query sanitization, and cassette replay (R3-K1/K2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from zem.contracts.models import (
    IntelItem,
    IntelResult,
    Signal,
    ToolCallContext,
)
from zem.intel import (
    CassetteMissError,
    IntelCache,
    RecordingEnricher,
    ReplayEnricher,
    TavilyEnricher,
    make_enricher,
    sanitize_query,
)
from zem.reasoning.prompts import build_user_prompt

CASSETTE_PATH = Path("tests/fixtures/intel_cassette.json")


def _ctx(tool: str = "pip_install", args: dict[str, Any] | None = None) -> ToolCallContext:
    return ToolCallContext(
        call_id="c-intel-1",
        session_id="s-intel-1",
        ts=datetime.now(UTC),
        server="pkg",
        tool=tool,
        arguments=args or {"package": "requests-security-patch"},
        signals=[
            Signal(
                detector="install_guard",
                code="unknown_package",
                weight=0.55,
                evidence="package 'requests-security-patch' not in lockfile",
            )
        ],
    )


# --------------------------------------------------------------------------- #
# 1. Outbound Query Sanitization                                              #
# --------------------------------------------------------------------------- #


def test_sanitize_query_strips_aws_and_github_secrets() -> None:
    raw = "pypi requests-security-patch AKIAIOSFODNN7EXAMPLE ghp_1234567890abcdef1234567890abcdef1234"
    cleaned = sanitize_query(raw)
    assert "AKIAIOSFODNN7EXAMPLE" not in cleaned
    assert "ghp_" not in cleaned
    assert "pypi requests-security-patch" in cleaned


def test_sanitize_query_strips_emails_and_local_paths() -> None:
    raw = "check C:\\Users\\admin\\.env and /home/ubuntu/.ssh/id_rsa for alice@corp.internal.com advisory"
    cleaned = sanitize_query(raw)
    assert "alice@corp.internal.com" not in cleaned
    assert "C:\\Users" not in cleaned
    assert "/home/ubuntu" not in cleaned
    assert "advisory" in cleaned


def test_sanitize_query_strips_url_query_params_and_traversal() -> None:
    raw = "https://webhook.site/drop?api_key=secret123&user=root ../../etc/passwd malware"
    cleaned = sanitize_query(raw)
    assert "api_key=secret123" not in cleaned
    assert "../../etc/passwd" not in cleaned
    assert "https://webhook.site/drop" in cleaned
    assert "malware" in cleaned


def test_sanitize_query_caps_length_and_neutralizes_tags() -> None:
    raw = "<script>alert(1)</script> " + ("pypi " * 80)
    cleaned = sanitize_query(raw)
    assert "<" not in cleaned and ">" not in cleaned
    assert len(cleaned) <= 200


def test_sanitize_query_returns_empty_when_only_secret() -> None:
    raw = "ghp_1234567890abcdef1234567890abcdef1234"
    assert sanitize_query(raw) == ""


# --------------------------------------------------------------------------- #
# 2. SQLite TTL Cache                                                         #
# --------------------------------------------------------------------------- #


def test_intel_cache_hit_miss_and_ttl_expiry(tmp_path: Path) -> None:
    db_file = tmp_path / "intel_cache.db"
    cache = IntelCache(db_file, ttl_s=60)
    q = "pypi requests-security-patch advisory"

    assert cache.get(q, now=1000.0) is None

    sample = [
        IntelItem(
            title="Malicious PyPI package report: requests-security-patch",
            url="https://security.snyk.io/package/pip/requests-security-patch",
            snippet="Known typosquatting package exfiltrating environment variables.",
            score=0.96,
        )
    ]
    cache.put(q, sample, now=1000.0)

    # Immediate hit within TTL
    hit = cache.get(q, now=1030.0)
    assert hit is not None
    assert len(hit) == 1
    assert hit[0].title == sample[0].title

    # Case & whitespace insensitivity
    hit_norm = cache.get("  PyPI   requests-security-patch ADVISORY ", now=1030.0)
    assert hit_norm is not None and len(hit_norm) == 1

    # Expired after TTL (1000 + 61 > 1060)
    expired = cache.get(q, now=1061.0)
    assert expired is None
    cache.close()


# --------------------------------------------------------------------------- #
# 3. TavilyEnricher Live HTTP Mock & Fail-Safe Behavior                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_tavily_enricher_parses_response_and_caches(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content.decode("utf-8"))
        # Verify secret was scrubbed before hitting Tavily API
        assert "AKIAIOSFODNN7EXAMPLE" not in body["query"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "PyPI Malware Advisory: requests-security-patch",
                        "url": "https://osv.dev/vulnerability/PYSEC-2026-991",
                        "content": "Package steals <env> tokens during setup.py install.",
                        "score": 0.94,
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        enricher = TavilyEnricher(
            api_key="tvly-test-key",
            cache_path=tmp_path / "cache.db",
            client=client,
        )
        # First call -> hits network
        res1 = await enricher.lookup("pypi requests-security-patch AKIAIOSFODNN7EXAMPLE")
        assert res1.cached is False
        assert len(res1.items) == 1
        assert res1.items[0].url == "https://osv.dev/vulnerability/PYSEC-2026-991"
        assert "<env>" not in res1.items[0].snippet  # angle brackets neutralized
        assert calls == 1

        # Second call -> served from SQLite cache (0 extra HTTP requests)
        res2 = await enricher.lookup("pypi requests-security-patch")
        assert res2.cached is True
        assert len(res2.items) == 1
        assert calls == 1
        enricher.cache.close()


@pytest.mark.asyncio
async def test_tavily_enricher_fails_safe_on_http_error(tmp_path: Path) -> None:
    def error_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "service unavailable"})

    transport = httpx.MockTransport(error_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        enricher = TavilyEnricher(
            api_key="tvly-test-key",
            cache_path=tmp_path / "cache.db",
            client=client,
        )
        res = await enricher.lookup("pypi reqeusts advisory")
        assert isinstance(res, IntelResult)
        assert res.items == []
        assert res.cached is False
        enricher.cache.close()


@pytest.mark.asyncio
async def test_tavily_enricher_skips_network_on_pure_secret_query(tmp_path: Path) -> None:
    enricher = TavilyEnricher(api_key="tvly-test-key", cache_path=tmp_path / "cache.db")
    res = await enricher.lookup("ghp_1234567890abcdef1234567890abcdef1234")
    assert res.query == "[redacted]"
    assert res.items == []
    enricher.cache.close()


# --------------------------------------------------------------------------- #
# 4. Offline Record/Replay Cassette & Prompt Integration                      #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_record_and_replay_cassette(tmp_path: Path) -> None:
    cassette = tmp_path / "test_intel_cassette.json"
    mock = make_enricher("mock")
    recorder = RecordingEnricher(mock, cassette)

    recorded = await recorder.lookup("requests-security-patch pip install advisory")
    assert len(recorded.items) >= 1
    assert cassette.exists()

    replayer = ReplayEnricher(cassette)
    replayed = await replayer.lookup("requests-security-patch pip install advisory")
    assert replayed.items == recorded.items

    with pytest.raises(CassetteMissError):
        await replayer.lookup("unrecorded query xyz")


@pytest.mark.asyncio
async def test_fixture_intel_cassette_and_prompt_injection_sandboxing() -> None:
    replayer = ReplayEnricher(CASSETTE_PATH)
    intel = await replayer.lookup("pypi requests-security-patch malware advisory")
    assert len(intel.items) >= 1
    assert intel.items[0].score > 0.5

    # Verify build_user_prompt wraps intel inside <intel><untrusted>...</untrusted></intel>
    ctx = _ctx()
    prompt = build_user_prompt(ctx, intel=intel)
    assert "<intel><untrusted>" in prompt
    assert "</untrusted></intel>" in prompt
    assert intel.items[0].url in prompt
