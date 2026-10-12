from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from zem.contracts.models import AuditEvent, Signal

SCHEMA = """CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, session_id TEXT NOT NULL,
  call_id TEXT NOT NULL, server TEXT NOT NULL, tool TEXT NOT NULL, decision TEXT NOT NULL,
  risk REAL NOT NULL, reasons TEXT NOT NULL, signals TEXT NOT NULL,
  latency_ms INTEGER NOT NULL, event_json TEXT NOT NULL)"""


def _scrub(event: AuditEvent) -> AuditEvent:
    """If a secret was detected, store neither the arguments nor any evidence text."""
    ctx = event.context
    if not any(s.detector == "secret_guard" for s in ctx.signals):
        return event
    signals = [s.model_copy(update={"evidence": "[redacted]"}) for s in ctx.signals]
    ctx = ctx.model_copy(update={"arguments": {"_redacted": "secret detected"}, "signals": signals})
    reasons = [f"{s.detector}/{s.code}" for s in signals if s.hard_deny]
    final = event.final.model_copy(update={"reasons": reasons})
    return event.model_copy(update={"context": ctx, "final": final})


class SqliteAudit:
    """Plain event log (R1). The hash chain arrives in R3."""

    def __init__(self, path: str | Path) -> None:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(p), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(SCHEMA)
        self.db.commit()

    def append(self, event: AuditEvent) -> None:
        ev = _scrub(event)
        sigs: list[Signal] = ev.context.signals
        self.db.execute(
            "INSERT INTO events (ts, session_id, call_id, server, tool, decision, risk,"
            " reasons, signals, latency_ms, event_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.ts.isoformat(),
                ev.session_id,
                ev.call_id,
                ev.context.server,
                ev.context.tool,
                ev.final.decision.value,
                ev.final.risk,
                json.dumps(ev.final.reasons),
                json.dumps(
                    [
                        {
                            "detector": s.detector,
                            "code": s.code,
                            "weight": s.weight,
                            "evidence": s.evidence,
                        }
                        for s in sigs
                    ]
                ),
                sum(ev.latency_breakdown_ms.values()),
                ev.model_dump_json(),
            ),
        )
        self.db.commit()

    def verify_chain(self) -> bool:
        raise NotImplementedError("hash chain arrives in R3")

    def recent(self, limit: int = 20, decision: str | None = None) -> list[dict[str, Any]]:
        where, args = ("WHERE decision = ?", [decision]) if decision else ("", [])
        rows = self.db.execute(
            f"SELECT * FROM (SELECT * FROM events {where} ORDER BY seq DESC LIMIT ?) ORDER BY seq",
            [*args, limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def after(self, seq: int, decision: str | None = None) -> list[dict[str, Any]]:
        where = "AND decision = ?" if decision else ""
        args: list[Any] = [seq] + ([decision] if decision else [])
        rows = self.db.execute(
            f"SELECT * FROM events WHERE seq > ? {where} ORDER BY seq", args
        ).fetchall()
        return [dict(r) for r in rows]
