"""Mock enricher — a fake Tavily threat intelligence lookup for tests and local dev.

Returns deterministic IntelResult objects based on simple keyword matching
so the test suite runs instantly without any network calls or API keys.
This implements the Enricher Protocol from zem.contracts.models.
"""
from __future__ import annotations

import time

from zem.contracts.models import IntelItem, IntelResult

# Known "malicious" domains/packages that the mock will flag
_KNOWN_BAD = {
    "evil.com": "Known malicious exfiltration endpoint.",
    "hacker-server.com": "Known attacker-controlled server.",
    "requests-security-patch": "Typosquatting package mimicking 'requests'.",
    "requests-toolbelt-x": "Unverified package with suspicious naming.",
    "paste.evil.example": "Known payload delivery domain.",
}


class MockEnricher:
    """Deterministic stand-in for the real Tavily enricher.

    Behaviour:
    - If the query contains any _KNOWN_BAD key → returns a flagging IntelResult.
    - Otherwise → returns an empty IntelResult (no findings, clean).

    This is intentionally simple.  The real TavilyEnricher will make live
    HTTP requests to Tavily's API; this mock just needs to let the pipeline
    plumbing be tested end-to-end without hitting an API.

    Security note: the real enricher MUST sanitise the query before sending
    it out (strip secrets, paths, credentials). That sanitiser lives in the
    real TavilyEnricher, not here.
    """

    async def lookup(self, query: str) -> IntelResult:
        start = time.monotonic()
        query_lower = query.lower()

        findings: list[IntelItem] = []

        for keyword, description in _KNOWN_BAD.items():
            if keyword in query_lower:
                findings.append(
                    IntelItem(
                        title=f"[mock] Threat advisory: {keyword}",
                        url=f"https://mock-threat-db.example/advisory/{keyword.replace(' ', '-')}",
                        snippet=description,
                        score=0.95,
                    )
                )

        latency = int((time.monotonic() - start) * 1000)

        return IntelResult(
            query=query,
            items=findings,
            cached=False,
            latency_ms=latency,
        )

