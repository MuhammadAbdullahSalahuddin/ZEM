"""Pin guard response hook (R3-I2).

Reads every tools/list answer, fingerprints each tool, scans it for poison, and withdraws
anything that changed or looks poisoned. The agent never sees a quarantined tool.

Safety rules for this file:
  - Descriptions are attacker text. They are NEVER copied into logs, audit rows or errors:
    only tool names (sanitised), hash prefixes and rule codes are.
  - Fail CLOSED: a malformed or oversized list is blocked (the proxy also blocks the list
    if this hook crashes).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from zem.audit.pin_store import PinStore
from zem.contracts.models import (
    AuditEvent,
    AuditSink,
    Decision,
    FinalDecision,
    Severity,
    Signal,
    ToolCallContext,
)
from zem.detectors._util import clean
from zem.detectors.pin_guard import PinState, safe_name
from zem.detectors.unicode_guard import _HARD, _SOFT
from zem.pipeline.egress import BUILTIN
from zem.policy.loader import PinSettings
from zem.protocol import jsonrpc
from zem.protocol.stdio_proxy import Pending, ResponseHook, log

MAX_SCAN_CHARS = 1_000_000
MAX_DEPTH = 40

_INJECTION = tuple(r for r in BUILTIN if r.pack == "injection")
_SENSITIVE = re.compile(
    r"(?i)\.ssh\b|\bid_(?:rsa|dsa|ecdsa|ed25519)\b|\.aws/credentials|/etc/(?:passwd|shadow)"
    r"|(?<![\w.])\.env\b|\bmcp\.json\b|claude_desktop_config"
)
_PRE_ACTION = re.compile(
    r"(?i)\bbefore\s{1,5}(?:using|calling|running|invoking|executing)\s{1,5}(?:this|the)\s{1,5}tool\b"
    r"|\b(?:first|also)\s{1,5}(?:read|send|call|fetch|include|attach|pass)\b"
    r"|\bpass\s{1,5}(?:its|the|their)\s{1,5}contents?\s{1,5}as\b"
)


class _TooDeep(Exception):
    pass


@dataclass(frozen=True)
class Hit:
    code: str
    hard: bool


def definition_hash(tool: dict[str, Any]) -> str:
    """Fingerprint of the WHOLE tool definition (name, description, schemas, annotations).
    Only `_meta` is ignored: servers put changing bookkeeping there."""
    body = {k: v for k, v in tool.items() if k != "_meta"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _strings(value: Any, depth: int = 0) -> Iterator[str]:
    if depth > MAX_DEPTH:
        raise _TooDeep
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                yield k
            yield from _strings(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, depth + 1)


def scan_definition(tool: dict[str, Any], max_description_chars: int) -> list[Hit]:
    """Look for poison in every string of a tool definition (descriptions of parameters too)."""
    hits: dict[str, bool] = {}

    def add(code: str, hard: bool) -> None:
        hits[code] = hits.get(code, False) or hard

    total = 0
    try:
        for raw in _strings(tool):
            total += len(raw)
            if total > MAX_SCAN_CHARS:
                add("oversized_definition", True)
                break
            if _HARD.search(raw):
                add("hidden_unicode", True)
            elif _SOFT.search(raw):
                add("zero_width_chars", False)
            text = clean(raw)  # defeats "ig<zero-width>nore previous instructions"
            for rule in _INJECTION:
                if rule.pattern.search(text):
                    add(f"injection_{rule.code}", True)
            if _SENSITIVE.search(text):
                add("sensitive_reference", False)
            if _PRE_ACTION.search(text):
                add("pre_action_instruction", False)
    except _TooDeep:
        add("too_deep", True)
    desc = tool.get("description")
    if isinstance(desc, str) and len(desc) > max_description_chars:
        add("oversized_description", False)
    if "sensitive_reference" in hits and "pre_action_instruction" in hits:
        add("exfil_instruction", True)  # "before using this tool, read ~/.ssh/..." shape
    return [Hit(c, h) for c, h in sorted(hits.items())]


@dataclass
class _Outcome:
    name: str
    code: str
    hard: bool  # True = the tool was withdrawn from the agent
    evidence: str


def _emit(
    audit: AuditSink | None,
    *,
    server: str,
    session_id: str,
    label: str,
    outcomes: list[_Outcome],
    ms: int,
) -> None:
    if audit is None or not outcomes:
        return
    denied = any(o.hard for o in outcomes)
    signals = [
        Signal(
            detector="pin_guard",
            code=o.code,
            weight=1.0 if o.hard else 0.3,
            severity=Severity.HIGH if o.hard else Severity.LOW,
            evidence=o.evidence[:200],
            hard_deny=o.hard,
        )
        for o in outcomes
    ]
    ctx = ToolCallContext(
        call_id=uuid4().hex,
        session_id=session_id,
        ts=datetime.now(UTC),
        server=server,
        tool=label,
        signals=signals,
    )
    reasons = [f"pin_guard/{o.code} ({safe_name(o.name)})" for o in outcomes]
    final = FinalDecision(
        decision=Decision.DENY if denied else Decision.ALLOW,
        risk=1.0 if denied else 0.2,
        reasons=reasons,
    )
    try:
        audit.append(
            AuditEvent(
                seq=0,
                ts=ctx.ts,
                session_id=session_id,
                call_id=ctx.call_id,
                context=ctx,
                final=final,
                latency_breakdown_ms={"pin": ms},
            )
        )
    except Exception as exc:  # noqa: BLE001
        log(f"pin audit write failed: {type(exc).__name__}")


def make_pin_hook(
    settings: PinSettings,
    *,
    store: PinStore,
    state: PinState,
    audit: AuditSink | None,
    server: str,
    session_id: str,
) -> ResponseHook:
    def _rules(hits: list[Hit]) -> str:
        return "rules: " + ",".join(h.code for h in hits) if hits else ""

    async def hook(msg: dict[str, Any], pending: Pending) -> dict[str, Any] | None:
        if pending.method != "tools/list" or "error" in msg:
            return None
        t0 = time.perf_counter()
        result = msg.get("result")
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(result, dict) or not isinstance(tools, list) or len(tools) > settings.max_tools:
            why = "pin_guard/malformed_or_oversized_tools_list"
            log(f"pins server={server} BLOCKED tools/list ({why})")
            _emit(
                audit, server=server, session_id=session_id, label="tools/list[pin]",
                outcomes=[_Outcome("tools/list", "malformed_tools_list", True, "list blocked")],
                ms=int((time.perf_counter() - t0) * 1000),
            )
            return jsonrpc.error_response(msg.get("id"), why)

        baseline = store.count(server) > 0  # had this server been pinned before this list?
        now = datetime.now(UTC).isoformat()
        seen: set[str] = set()
        keep: list[Any] = []
        outcomes: list[_Outcome] = []
        pinned = 0

        for tool in tools:
            name = tool.get("name") if isinstance(tool, dict) else None
            if not isinstance(name, str) or not name:
                outcomes.append(_Outcome("?", "malformed_tool", True, "entry dropped"))
                continue
            if name in seen:
                outcomes.append(_Outcome(name, "duplicate_name", True, "second entry dropped"))
                continue
            seen.add(name)
            digest = definition_hash(tool)
            row = store.get(server, name)

            if row is None:  # first sighting
                hits = scan_definition(tool, settings.max_description_chars)
                hard = [h for h in hits if h.hard]
                if hard and settings.on_poison == "quarantine":
                    store.insert_new(server, name, digest, now, "quarantined", "poisoned_definition")
                    state.quarantined[name] = "poisoned_definition"
                    outcomes.append(_Outcome(name, "poisoned_definition", True, _rules(hard)))
                    continue
                if baseline and settings.on_new_tool == "quarantine":
                    store.insert_new(server, name, digest, now, "quarantined", "new_tool")
                    state.quarantined[name] = "new_tool"
                    outcomes.append(_Outcome(name, "new_tool", True, "appeared after the server was pinned"))
                    continue
                store.insert_new(server, name, digest, now)
                pinned += 1
                if hits:
                    code = "poisoned_definition" if hard else "suspicious_definition"
                    outcomes.append(_Outcome(name, code, False, _rules(hits) + " (flag only)"))
                if baseline:
                    outcomes.append(_Outcome(name, "new_tool", False, "appeared after the server was pinned"))
                keep.append(tool)
                continue

            if row.status == "quarantined":  # stays withheld, even if it changed back
                state.quarantined[name] = row.reason or "quarantined"
                continue
            if digest == row.hash:  # unchanged and approved
                keep.append(tool)
                continue

            hits = scan_definition(tool, settings.max_description_chars)
            evidence = f"hash {row.hash[:12]} -> {digest[:12]}"
            if hits:
                evidence += "; " + _rules(hits)
            if settings.on_change == "quarantine":
                store.quarantine(server, name, digest, "definition_changed")
                state.quarantined[name] = "definition_changed"
                outcomes.append(_Outcome(name, "definition_changed", True, evidence))
                continue
            outcomes.append(_Outcome(name, "definition_changed", False, evidence + " (flag only)"))
            keep.append(tool)

        ms = int((time.perf_counter() - t0) * 1000)
        by_tool: dict[str, list[_Outcome]] = {}
        for o in outcomes:
            by_tool.setdefault(o.name, []).append(o)
        for name, group in by_tool.items():
            _emit(
                audit, server=server, session_id=session_id,
                label=f"{safe_name(name)}[pin]", outcomes=group, ms=ms,
            )
        if pinned:
            _emit(
                audit, server=server, session_id=session_id, label="tools/list[pin]",
                outcomes=[_Outcome("tools/list", "pinned_new_tools", False,
                                   f"{pinned} tool(s) pinned (trust on first use)")],
                ms=ms,
            )
        withdrawn = len(tools) - len(keep)
        log(f"pins server={server} listed={len(tools)} pinned={pinned} withdrawn={withdrawn} ms={ms}")
        if withdrawn == 0:
            return None
        return {**msg, "result": {**result, "tools": keep}}

    return hook
