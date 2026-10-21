"""Pin store (R3-I2): remembers the fingerprint of every tool definition a human has approved.

status 'ok'          : the stored hash is the approved definition.
status 'quarantined' : the tool is withheld from the agent until `zem pins approve`.
                       pending_hash holds the new (unapproved) definition after a change.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """CREATE TABLE IF NOT EXISTS pins (
  server TEXT NOT NULL, tool TEXT NOT NULL, hash TEXT NOT NULL,
  pending_hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ok',
  reason TEXT NOT NULL DEFAULT '', first_seen TEXT NOT NULL,
  PRIMARY KEY (server, tool))"""


@dataclass(frozen=True)
class Pin:
    server: str
    tool: str
    hash: str
    pending_hash: str
    status: str
    reason: str
    first_seen: str


class PinStore:
    def __init__(self, path: str | Path) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Several `zem wrap` processes may share one file, so wait for locks instead of failing.
        self.db = sqlite3.connect(str(p), check_same_thread=False, timeout=5.0)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute(SCHEMA)
        self.db.commit()

    @staticmethod
    def _pin(row: sqlite3.Row) -> Pin:
        return Pin(
            row["server"], row["tool"], row["hash"], row["pending_hash"],
            row["status"], row["reason"], row["first_seen"],
        )

    def get(self, server: str, tool: str) -> Pin | None:
        row = self.db.execute(
            "SELECT * FROM pins WHERE server = ? AND tool = ?", (server, tool)
        ).fetchone()
        return self._pin(row) if row else None

    def count(self, server: str) -> int:
        row = self.db.execute("SELECT COUNT(*) AS n FROM pins WHERE server = ?", (server,)).fetchone()
        return int(row["n"])

    def insert_new(
        self, server: str, tool: str, digest: str, now: str, status: str = "ok", reason: str = ""
    ) -> bool:
        """First sighting. If another process got there first, theirs wins (returns False)."""
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO pins (server, tool, hash, status, reason, first_seen)"
                " VALUES (?,?,?,?,?,?)",
                (server, tool, digest, status, reason, now),
            )
        return cur.rowcount == 1

    def quarantine(self, server: str, tool: str, pending_hash: str, reason: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE pins SET status = 'quarantined', pending_hash = ?, reason = ?"
                " WHERE server = ? AND tool = ?",
                (pending_hash, reason, server, tool),
            )

    def approve(self, server: str, tool: str) -> bool:
        with self.db:
            cur = self.db.execute(
                "UPDATE pins SET hash = CASE WHEN pending_hash != '' THEN pending_hash ELSE hash END,"
                " pending_hash = '', status = 'ok', reason = '' WHERE server = ? AND tool = ?",
                (server, tool),
            )
        return cur.rowcount == 1

    def forget(self, server: str, tool: str | None = None) -> int:
        with self.db:
            if tool is None:
                cur = self.db.execute("DELETE FROM pins WHERE server = ?", (server,))
            else:
                cur = self.db.execute(
                    "DELETE FROM pins WHERE server = ? AND tool = ?", (server, tool)
                )
        return cur.rowcount

    def quarantined(self, server: str) -> dict[str, str]:
        rows = self.db.execute(
            "SELECT tool, reason FROM pins WHERE server = ? AND status = 'quarantined'", (server,)
        ).fetchall()
        return {r["tool"]: r["reason"] or "quarantined" for r in rows}

    def rows(self, server: str | None = None) -> list[Pin]:
        if server is None:
            found = self.db.execute("SELECT * FROM pins ORDER BY server, tool").fetchall()
        else:
            found = self.db.execute(
                "SELECT * FROM pins WHERE server = ? ORDER BY tool", (server,)
            ).fetchall()
        return [self._pin(r) for r in found]
