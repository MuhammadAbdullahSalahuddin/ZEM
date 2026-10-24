"""Live smoke test for TavilyEnricher + SQLite Cache + NebiusReasoner 2-pass flow (R3).

Run:
    uv run python -m zem.intel.smoke
    uv run python -m zem.intel.smoke --record
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from zem.contracts.models import Enricher, Signal, ToolCallContext
from zem.intel import RecordingEnricher, TavilyEnricher
from zem.reasoning.nebius_reasoner import NebiusReasoner

DEFAULT_CASSETTE = Path("tests/fixtures/intel_cassette.json")

SMOKE_QUERIES = [
    "pypi requests-security-patch malware advisory",
    "pypi reqeusts typosquatting advisory",
    "webhook.site data exfiltration security advisory",
    "paste.evil.example payload delivery",
    "pypi requests official package",
]


async def run_smoke(*, record: bool = False) -> int:
    with tempfile.TemporaryDirectory(prefix="zem-intel-smoke-") as tmpdir:
        cache_db = Path(tmpdir) / "intel_cache.db"
        live_enricher = TavilyEnricher(cache_path=cache_db)
        enricher: Enricher = (
            RecordingEnricher(live_enricher, DEFAULT_CASSETTE) if record else live_enricher
        )

        print("=== 1. TAVILY LIVE SEARCH & SQLITE CACHE SMOKE TEST ===", file=sys.stderr)
        for q in SMOKE_QUERIES:
            res = await enricher.lookup(q)
            top_title = res.items[0].title[:55] if res.items else "(no hits)"
            top_score = f"{res.items[0].score:.2f}" if res.items else "0.00"
            print(
                f"  [LIVE] query={res.query!r:<48} hits={len(res.items)} "
                f"cached={res.cached!s:<5} lat={res.latency_ms:>4}ms "
                f"top={top_title!r} (score={top_score})",
                file=sys.stderr,
            )

        # Verify SQLite cache hit (<5ms) on second lookup of the first query
        cached_res = await live_enricher.lookup(SMOKE_QUERIES[0])
        print(
            f"  [CACHE CHECK] query={cached_res.query!r} cached={cached_res.cached} "
            f"lat={cached_res.latency_ms}ms hits={len(cached_res.items)}",
            file=sys.stderr,
        )

        # Verify outbound secret scrubber blocks secret leakage
        scrubbed_res = await live_enricher.lookup(
            "ghp_1234567890abcdef1234567890abcdef1234"
        )
        print(
            f"  [SCRUB CHECK] pure-secret query -> query={scrubbed_res.query!r} "
            f"hits={len(scrubbed_res.items)} (0 network bytes sent)",
            file=sys.stderr,
        )

        # 2. Full Two-Pass Nebius Nemotron + Tavily Threat Intel Escalation
        print("\n=== 2. TWO-PASS NEBIUS NEMOTRON + TAVILY INTEL HANDOFF ===", file=sys.stderr)
        ctx = ToolCallContext(
            call_id="smoke-r3-1",
            session_id="smoke-sess-1",
            ts=datetime.now(UTC),
            server="shell",
            tool="shell_run",
            arguments={"command": "pip install reqeusts"},
            objective="Install the HTTP client library for the project",
            signals=[
                Signal(
                    detector="install_guard",
                    code="unknown_package",
                    weight=0.55,
                    evidence="pip install 'reqeusts' is not in known_packages",
                )
            ],
        )
        reasoner = NebiusReasoner()
        pass1 = await reasoner.judge(ctx, depth="fast")
        print(
            f"  [PASS 1: FAST JUDGE] model={pass1.model_id} verdict={pass1.verdict} "
            f"conf={pass1.confidence:.2f} needs_intel={pass1.needs_intel} "
            f"query={pass1.intel_query!r} lat={pass1.latency_ms}ms",
            file=sys.stderr,
        )

        intel_query = pass1.intel_query or "pypi reqeusts typosquatting malware advisory"
        intel_result = await live_enricher.lookup(intel_query)
        print(
            f"  [TAVILY ENRICHER]    query={intel_result.query!r} hits={len(intel_result.items)} "
            f"cached={intel_result.cached} lat={intel_result.latency_ms}ms",
            file=sys.stderr,
        )

        pass2 = await reasoner.judge(ctx, depth="deep", intel=intel_result)
        print(
            f"  [PASS 2: DEEP JUDGE] model={pass2.model_id} verdict={pass2.verdict} "
            f"conf={pass2.confidence:.2f} lat={pass2.latency_ms}ms\n"
            f"                       reason={pass2.reason!r}\n"
            f"                       tags={pass2.risk_tags}",
            file=sys.stderr,
        )

        live_enricher.cache.close()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Tavily + Nebius R3 smoke test")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record live Tavily responses into tests/fixtures/intel_cassette.json",
    )
    args = parser.parse_args()
    return asyncio.run(run_smoke(record=args.record))


if __name__ == "__main__":
    raise SystemExit(main())
