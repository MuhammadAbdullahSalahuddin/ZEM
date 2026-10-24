"""SQLite TTL cache for threat intelligence lookups (R3-K1).

Caches sanitized Tavily search queries locally so repeated checks for the same
package, domain, or CVE resolve in <1ms without spending API credits.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from zem.contracts.models import IntelItem

DEFAULT_TTL_S = 86_400  # 24 hours


def query_cache_key(sanitized_query: str) -> str:
    """Stable SHA-256 key for a normalized, sanitized query string."""
    normalized = " ".join(sanitized_query.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class IntelCache:
    """Lightweight SQLite TTL cache storing serialized IntelItem lists."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        *,
        ttl_s: int = DEFAULT_TTL_S,
    ) -> None:
        self.db_path = str(db_path)
        self.ttl_s = ttl_s
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS intel_cache (
                cache_key TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                items_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, sanitized_query: str, *, now: float | None = None) -> list[IntelItem] | None:
        """Return cached IntelItems if present and not expired, else None."""
        key = query_cache_key(sanitized_query)
        current_time = time.time() if now is None else now
        row = self._conn.execute(
            "SELECT items_json, created_at FROM intel_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        items_json, created_at = row
        if current_time - float(created_at) > self.ttl_s:
            self._conn.execute("DELETE FROM intel_cache WHERE cache_key = ?", (key,))
            self._conn.commit()
            return None
        try:
            raw_list = json.loads(items_json)
            return [IntelItem.model_validate(item) for item in raw_list]
        except Exception:  # noqa: BLE001
            return None

    def put(
        self,
        sanitized_query: str,
        items: list[IntelItem],
        *,
        now: float | None = None,
    ) -> None:
        """Store IntelItems for a sanitized query."""
        key = query_cache_key(sanitized_query)
        current_time = time.time() if now is None else now
        payload = json.dumps([item.model_dump() for item in items], sort_keys=True)
        self._conn.execute(
            """
            INSERT INTO intel_cache (cache_key, query, items_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                query = excluded.query,
                items_json = excluded.items_json,
                created_at = excluded.created_at
            """,
            (key, sanitized_query, payload, current_time),
        )
        self._conn.commit()

    def clear(self) -> None:
        """Remove all cached entries."""
        self._conn.execute("DELETE FROM intel_cache")
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

