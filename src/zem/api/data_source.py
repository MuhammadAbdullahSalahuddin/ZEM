from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from zem.audit.store import SqliteAudit
from zem.contracts.models import AuditEvent

logger = logging.getLogger(__name__)

# Default location for fake events dataset (fallback)
DEFAULT_FAKE_EVENTS_PATH = (
    Path(__file__).resolve().parents[3] / "web" / "src" / "fake_events.json"
)

# Default location for real SQLite audit database
DEFAULT_DB_PATH = Path(os.environ.get("ZEM_DB", str(Path.home() / ".zem" / "zem.db")))


def _row_to_audit_event(row: dict[str, Any]) -> AuditEvent | None:
    """Deserialize a SQLite audit row into an AuditEvent model.

    Fails closed: returns None on any corrupted data or validation failure.
    """
    raw_json = row.get("event_json")
    if not raw_json:
        return None
    try:
        ev = AuditEvent.model_validate_json(raw_json)
        # Ensure sequence number matches database auto-increment seq
        if "seq" in row and row["seq"] is not None and ev.seq != row["seq"]:
            ev = ev.model_copy(update={"seq": int(row["seq"])})
        return ev
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("Failed to deserialize audit event from DB row: %s", exc)
        return None


def _load_fake_events(file_path: Path | None = None) -> list[AuditEvent]:
    """Load audit events from fake_events.json fallback file.

    Ensures context inherits call_id, session_id, and ts if omitted.
    """
    path = file_path or DEFAULT_FAKE_EVENTS_PATH
    if not path.is_file():
        logger.warning("Decisions fake events file not found: %s", path)
        return []

    try:
        content = path.read_text(encoding="utf-8")
        data: Any = json.loads(content)
        if not isinstance(data, list):
            logger.warning("Decisions fake events must be a JSON list, got %s", type(data))
            return []

        events: list[AuditEvent] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # Inherit top-level metadata into context if missing in raw JSON
            ctx = item.get("context")
            if isinstance(ctx, dict):
                if "call_id" not in ctx and "call_id" in item:
                    ctx["call_id"] = item["call_id"]
                if "session_id" not in ctx and "session_id" in item:
                    ctx["session_id"] = item["session_id"]
                if "ts" not in ctx and "ts" in item:
                    ctx["ts"] = item["ts"]
            try:
                events.append(AuditEvent.model_validate(item))
            except (ValidationError, ValueError, TypeError) as val_err:
                logger.debug("Skipping invalid AuditEvent item: %s", val_err)
                continue
        return events
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error("Failed to read fake decisions from %s: %s", path, exc)
        return []


def get_decisions(
    limit: int = 50,
    db_path: Path | str | None = None,
    file_path: Path | None = None,
) -> list[AuditEvent]:
    """Retrieve audit decisions, sorted newest first.

    If SQLite database exists and has events, queries SQLite.
    Otherwise, seamlessly falls back to fake_events.json.
    Clamps limit to [1, 200].
    """
    clamped_limit = max(1, min(limit, 200))
    resolved_db = Path(db_path or DEFAULT_DB_PATH).expanduser()

    # Try SQLite first if the database file exists
    if resolved_db.is_file():
        try:
            store = SqliteAudit(resolved_db)
            rows = store.recent(clamped_limit)
            if rows:
                events: list[AuditEvent] = []
                for r in rows:
                    ev = _row_to_audit_event(r)
                    if ev:
                        events.append(ev)
                # Sort newest first (descending by timestamp and sequence)
                events.sort(key=lambda ev: (ev.ts, ev.seq), reverse=True)
                return events[:clamped_limit]
        except (sqlite3.Error, OSError, ValueError, ValidationError) as exc:
            logger.warning("Could not read from SQLite audit store %s: %s", resolved_db, exc)

    # Fallback to fake_events.json
    events = _load_fake_events(file_path)
    events.sort(key=lambda ev: (ev.ts, ev.seq), reverse=True)
    return events[:clamped_limit]


def get_decision_by_id(
    call_id: str,
    db_path: Path | str | None = None,
    file_path: Path | None = None,
) -> AuditEvent | None:
    """Find a specific decision by call_id.

    Checks SQLite store first if available, then falls back to fake_events.json.
    Returns None if not found.
    """
    resolved_db = Path(db_path or DEFAULT_DB_PATH).expanduser()
    if resolved_db.is_file():
        try:
            store = SqliteAudit(resolved_db)
            row = store.db.execute(
                "SELECT seq, event_json FROM events WHERE call_id = ? ORDER BY seq DESC LIMIT 1",
                (call_id,),
            ).fetchone()
            if row:
                ev = _row_to_audit_event(dict(row))
                if ev:
                    return ev
        except (sqlite3.Error, OSError, ValueError, ValidationError) as exc:
            logger.warning("Error querying SQLite for call_id %s: %s", call_id, exc)

    # Fallback search in fake events
    fake_events = _load_fake_events(file_path)
    for ev in fake_events:
        if ev.call_id == call_id:
            return ev

    return None


def get_new_decisions(
    after_seq: int,
    db_path: Path | str | None = None,
) -> list[AuditEvent]:
    """Retrieve new decisions recorded after the specified sequence number.

    Used by SSE /api/stream endpoint.
    """
    resolved_db = Path(db_path or DEFAULT_DB_PATH).expanduser()
    if not resolved_db.is_file():
        return []

    try:
        store = SqliteAudit(resolved_db)
        rows = store.after(after_seq)
        events: list[AuditEvent] = []
        for r in rows:
            ev = _row_to_audit_event(r)
            if ev:
                events.append(ev)
        return events
    except (sqlite3.Error, OSError, ValueError, ValidationError) as exc:
        logger.warning(
            "Error reading decisions after seq %s from %s: %s", after_seq, resolved_db, exc
        )
        return []


def get_latest_seq(
    db_path: Path | str | None = None,
    file_path: Path | None = None,
) -> int:
    """Retrieve the highest sequence number currently recorded."""
    resolved_db = Path(db_path or DEFAULT_DB_PATH).expanduser()
    if resolved_db.is_file():
        try:
            store = SqliteAudit(resolved_db)
            row = store.db.execute("SELECT MAX(seq) AS max_seq FROM events").fetchone()
            if row and row["max_seq"] is not None:
                return int(row["max_seq"])
        except (sqlite3.Error, OSError, ValueError):
            logger.debug("Could not fetch latest seq from SQLite store %s", resolved_db)

    # Check fake events for max seq
    fake_events = _load_fake_events(file_path)
    if fake_events:
        return max(ev.seq for ev in fake_events)

    return 0
