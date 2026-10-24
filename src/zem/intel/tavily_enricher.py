"""TavilyEnricher: live threat-intelligence lookup via Tavily Search API (R3-K1).

Implements the Enricher protocol from zem.contracts.models:
    async def lookup(self, query: str) -> IntelResult

Security design rules:
1. Outbound Query Sanitization: Never leak secrets, credentials, email addresses,
   or local filesystem paths to an external search API. Queries are scrubbed
   before caching or network transmission.
2. SQLite TTL Caching: Repeated queries for the same package or domain return
   in <1ms with cached=True and zero API credit cost.
3. Fail-Safe Resilience: Network timeouts, HTTP errors, or malformed responses
   never crash the gateway pipeline; they log to stderr and return an empty
   IntelResult so the policy engine's deterministic fallback remains in control.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from zem.contracts.models import IntelItem, IntelResult
from zem.detectors.secret_guard import PATTERNS as SECRET_PATTERNS
from zem.intel.cache import DEFAULT_TTL_S, IntelCache

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_QUERY_CHARS = 200
MAX_RESULTS = 5
MAX_TITLE_CHARS = 160
MAX_SNIPPET_CHARS = 350
DEFAULT_TIMEOUT_S = 4.0

# Additional outbound scrubbing patterns to prevent accidental data exfiltration via search queries
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_UNIX_ABS_PATH_RE = re.compile(r"(?:^|\s)(/(?:Users|home|etc|var|tmp|opt|root|workspace|private)[^\s\"']*)")
_WIN_ABS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s\"']*")
_TRAVERSAL_RE = re.compile(r"(?:\.\./|\.\.\\)+[^\s\"']*")
_URL_QUERY_RE = re.compile(r"(https?://[^\s?#]+)[?#][^\s]*")
_LONG_HEX_OR_B64_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b")


class TavilySettings(BaseSettings):
    """Loads TAVILY_API_KEY from environment variables or local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    tavily_api_key: SecretStr | None = None


def sanitize_query(raw_query: str) -> str:
    """Scrub secrets, paths, emails, and query strings from an outbound search query.

    Returns an empty string if nothing safe remains after scrubbing.
    """
    text = raw_query.strip()
    if not text:
        return ""

    # 1. Redact all known secret formats from SecretGuard
    for _code, pattern, _weight, _hard in SECRET_PATTERNS:
        text = pattern.sub(" ", text)

    # 2. Strip URL query parameters/fragments (e.g. https://evil.com/cb?token=secret -> https://evil.com/cb)
    text = _URL_QUERY_RE.sub(r"\1", text)

    # 3. Strip emails, local paths, path traversals, and high-entropy token blobs
    text = _EMAIL_RE.sub(" ", text)
    text = _WIN_ABS_PATH_RE.sub(" ", text)
    text = _UNIX_ABS_PATH_RE.sub(" ", text)
    text = _TRAVERSAL_RE.sub(" ", text)
    text = _LONG_HEX_OR_B64_RE.sub(" ", text)

    # 4. Neutralize angle brackets and collapse whitespace
    text = text.replace("<", " ").replace(">", " ")
    cleaned = " ".join(text.split())
    return cleaned[:MAX_QUERY_CHARS]


def _clean_text(text: str, limit: int) -> str:
    """Strip angle brackets, collapse whitespace, and cap length."""
    cleaned = " ".join(str(text).replace("<", "\u2039").replace(">", "\u203a").split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "...[truncated]"


class TavilyEnricher:
    """Live threat intelligence enricher backed by Tavily Search API and SQLite cache."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cache: IntelCache | None = None,
        cache_path: str | Path | None = None,
        ttl_s: int = DEFAULT_TTL_S,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_results: int = MAX_RESULTS,
        search_depth: str = "basic",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        key = api_key
        if key is None:
            secret = TavilySettings().tavily_api_key
            key = secret.get_secret_value().strip() if secret else None
        self._api_key = key or ""
        self.timeout_s = timeout_s
        self.max_results = max_results
        self.search_depth = search_depth
        self._client = client

        if cache is not None:
            self.cache = cache
        elif cache_path is not None:
            self.cache = IntelCache(cache_path, ttl_s=ttl_s)
        else:
            default_db = Path.home() / ".zem" / "intel_cache.db"
            self.cache = IntelCache(default_db, ttl_s=ttl_s)

    async def lookup(self, query: str) -> IntelResult:
        """Sanitize query, check cache, or query Tavily Search API."""
        start = time.monotonic()
        sanitized = sanitize_query(query)
        if not sanitized:
            return IntelResult(
                query="[redacted]",
                items=[],
                cached=False,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        # 1. Check local SQLite cache first
        cached_items = self.cache.get(sanitized)
        if cached_items is not None:
            return IntelResult(
                query=sanitized,
                items=cached_items,
                cached=True,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        # 2. If no API key is configured, fail safe with empty result
        if not self._api_key and self._client is None:
            logger.warning("Tavily lookup skipped: TAVILY_API_KEY is not configured")
            return IntelResult(
                query=sanitized,
                items=[],
                cached=False,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": sanitized,
            "search_depth": self.search_depth,
            "max_results": self.max_results,
            "include_answer": False,
            "include_raw_content": False,
        }

        try:
            if self._client is not None:
                resp = await self._client.post(
                    TAVILY_SEARCH_URL,
                    json=payload,
                    timeout=self.timeout_s,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_s) as http:
                    resp = await http.post(TAVILY_SEARCH_URL, json=payload)

            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Tavily lookup failed query=%r error=%s",
                sanitized,
                type(exc).__name__,
            )
            return IntelResult(
                query=sanitized,
                items=[],
                cached=False,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        raw_results = data.get("results") if isinstance(data, dict) else []
        if not isinstance(raw_results, list):
            raw_results = []

        items: list[IntelItem] = []
        for entry in raw_results[: self.max_results]:
            if not isinstance(entry, dict):
                continue
            title = _clean_text(entry.get("title") or "Untitled advisory", MAX_TITLE_CHARS)
            url = str(entry.get("url") or "").strip()
            snippet = _clean_text(entry.get("content") or entry.get("snippet") or "", MAX_SNIPPET_CHARS)
            try:
                score = float(entry.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(1.0, score))
            if url:
                items.append(
                    IntelItem(
                        title=title,
                        url=url,
                        snippet=snippet,
                        score=score,
                    )
                )

        # Cache successful lookups (including clean empty results)
        self.cache.put(sanitized, items)

        return IntelResult(
            query=sanitized,
            items=items,
            cached=False,
            latency_ms=int((time.monotonic() - start) * 1000),
        )


# Alias for convenience
TavilyIntel = TavilyEnricher

