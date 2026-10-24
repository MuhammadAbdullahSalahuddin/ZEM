"""Record/replay cassette wrapper for Enricher (R3-K2).

Allows deterministic, zero-network CI testing of Tavily threat intelligence
lookups and two-pass Reasoner + Enricher security flows.
"""

from __future__ import annotations

import json
from pathlib import Path

from zem.contracts.models import Enricher, IntelResult
from zem.intel.cache import query_cache_key
from zem.intel.tavily_enricher import sanitize_query


class CassetteMissError(KeyError):
    """Raised when a query is not found in the offline intel cassette."""


class RecordingEnricher:
    """Wraps a live Enricher and records every lookup result to a JSON cassette."""

    def __init__(self, inner: Enricher, cassette_path: str | Path) -> None:
        self.inner = inner
        self.path = Path(cassette_path)
        self._entries: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._entries = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._entries = {}

    async def lookup(self, query: str) -> IntelResult:
        res = await self.inner.lookup(query)
        sanitized = sanitize_query(query) or "[redacted]"
        key = query_cache_key(sanitized)
        self._entries[key] = res.model_dump()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._entries, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return res


class ReplayEnricher:
    """Replays recorded IntelResult objects from a JSON cassette with zero network calls."""

    def __init__(self, cassette_path: str | Path) -> None:
        self.path = Path(cassette_path)
        if not self.path.exists():
            raise FileNotFoundError(f"Intel cassette not found: {self.path}")
        self._entries: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8"))

    async def lookup(self, query: str) -> IntelResult:
        sanitized = sanitize_query(query) or "[redacted]"
        key = query_cache_key(sanitized)
        if key not in self._entries:
            raise CassetteMissError(f"No recorded intel entry for query={sanitized!r} (key={key[:12]})")
        return IntelResult.model_validate(self._entries[key])

