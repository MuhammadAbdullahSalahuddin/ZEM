"""ZEM Threat Intelligence package (R3).

Provides live Tavily Search API enrichment, SQLite TTL caching, outbound
query sanitization, and deterministic cassette replay.
"""

from __future__ import annotations

import os
from pathlib import Path

from zem.contracts.models import Enricher
from zem.intel.cache import IntelCache, query_cache_key
from zem.intel.mock_enricher import MockEnricher
from zem.intel.record_replay import (
    CassetteMissError,
    RecordingEnricher,
    ReplayEnricher,
)
from zem.intel.tavily_enricher import (
    TavilyEnricher,
    TavilyIntel,
    TavilySettings,
    sanitize_query,
)


def make_enricher(
    mode: str | None = None,
    *,
    cassette_path: str | Path | None = None,
) -> Enricher:
    """Factory returning the requested Enricher implementation (tavily | mock | replay)."""
    selected = (mode or os.environ.get("ZEM_ENRICHER", "mock")).strip().lower()
    if selected == "tavily":
        return TavilyEnricher()
    if selected == "replay":
        path = cassette_path or Path("tests/fixtures/intel_cassette.json")
        return ReplayEnricher(path)
    return MockEnricher()


__all__ = [
    "CassetteMissError",
    "IntelCache",
    "MockEnricher",
    "RecordingEnricher",
    "ReplayEnricher",
    "TavilyEnricher",
    "TavilyIntel",
    "TavilySettings",
    "make_enricher",
    "query_cache_key",
    "sanitize_query",
]

