"""Egress filter (R3-I3): reads what a tool sends BACK and scrubs it.

Rules live in the policy YAML (see EgressSettings). Built-in packs: secrets, pii_ids,
contact, injection. Actions: redact | flag | block | off.

Safety rules for this file:
  - The audit log gets counts and rule names only, NEVER the matched text.
  - Fail CLOSED: a result too big or too deeply nested to inspect is blocked.
  - Every pattern is bounded so a hostile result cannot make scanning quadratic.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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
from zem.detectors.secret_guard import PATTERNS
from zem.policy.loader import EgressSettings
from zem.protocol import jsonrpc
from zem.protocol.stdio_proxy import Pending, ResponseHook, log

EGRESS_METHODS = frozenset({"tools/call", "resources/read", "prompts/get"})
MAX_DEPTH = 40


@dataclass(frozen=True)
class Rule:
    pack: str  # "secrets" | "pii_ids" | "contact" | "injection" | a custom rule's name
    code: str  # the label in [REDACTED:code]
    pattern: re.Pattern[str]
    luhn: bool = False  # only count the match if it passes the card-number checksum


# secret_guard only matches the "-----BEGIN ... PRIVATE KEY-----" line. Redacting just that
# line would leave the key body readable, so here we match the whole block (bounded).
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN ((?:[A-Z]+ )*)PRIVATE KEY-----[\s\S]{0,16384}?-----END \1PRIVATE KEY-----"
)


def _builtin_rules() -> tuple[Rule, ...]:
    rules: list[Rule] = [Rule("secrets", "private_key", _PRIVATE_KEY_BLOCK)]
    rules += [Rule("secrets", code, pat) for code, pat, _w, _h in PATTERNS]
    rules += [
        Rule("pii_ids", "cnic", re.compile(r"\b\d{5}-\d{7}-\d\b")),
        Rule(
            "pii_ids",
            "credit_card",
            re.compile(
                r"\b(?:\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,7}|\d{4}[ -]\d{6}[ -]\d{5}|\d{15,16})\b"
            ),
            luhn=True,
        ),
        Rule(
            "pii_ids",
            "phone_intl",
            re.compile(r"(?<![\w+])\+\d{1,3}[ -]?\d{2,4}[ -]?\d{3,4}[ -]?\d{3,4}\b"),
        ),
        Rule("pii_ids", "phone_pk", re.compile(r"(?<![\w-])03\d{2}[ -]?\d{7}\b")),
        Rule(
            "contact",
            "email",
            re.compile(
                r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}"
                r"(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24}\b"
            ),
        ),
        Rule(
            "injection",
            "ignore_instructions",
            re.compile(
                r"(?i)\bignore\s{1,5}(?:all\s{1,5}|any\s{1,5})?"
                r"(?:prior|previous|above|earlier)\s{1,5}(?:instructions|rules|prompts?)\b"
            ),
        ),
        Rule(
            "injection",
            "addresses_ai",
            re.compile(
                r"(?i)\b(?:ai|llm)\s{0,3}(?:agent|assistant)\s{0,3}:"
                r"|\bassistant\s{0,3}:\s{0,3}(?:ignore|run|execute|send|post|read)\b"
            ),
        ),
        Rule("injection", "important_tag", re.compile(r"(?i)<\s{0,3}important\s{0,3}>")),
        Rule(
            "injection",
            "hide_from_user",
            re.compile(
                r"(?i)\bdo\s{1,3}not\s{1,3}(?:tell|inform|mention|show)\s{1,3}"
                r"(?:this\s{1,3}to\s{1,3})?the\s{1,3}user\b"
            ),
        ),
    ]
    return tuple(rules)


BUILTIN = _builtin_rules()
Plan = list[tuple[Rule, str]]


def build_plan(settings: EgressSettings) -> Plan:
    actions = {
        "secrets": settings.secrets,
        "pii_ids": settings.pii_ids,
        "contact": settings.contact,
        "injection": settings.injection,
    }
    plan: Plan = [(r, actions[r.pack]) for r in BUILTIN if actions[r.pack] != "off"]
    for c in settings.custom:
        if c.action != "off":
            plan.append((Rule(c.name, c.name, re.compile(c.pattern)), c.action))
    return plan


def _luhn_ok(text: str) -> bool:
    digits = [int(c) for c in text if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class TooLarge(Exception):
    """Result too big or too deeply nested to inspect safely."""


def _is_binary(parent: Any, key: str) -> bool:
    """Image/audio payloads and resource blobs are base64: regexes would corrupt them."""
    if not isinstance(parent, dict):
        return False
    if key == "data" and parent.get("type") in ("image", "audio"):
        return True
    return key == "blob" and "uri" in parent


class _Scan:
    def __init__(self, plan: Plan, allowed: frozenset[str], budget: int) -> None:
        self.plan = [(r, a) for r, a in plan if r.pack not in allowed]
        self.budget = budget
        self.redacted: Counter[str] = Counter()
        self.flagged: Counter[str] = Counter()
        self.blocked: Counter[str] = Counter()
        self.n_redacted = 0
        self.unscanned = 0

    def _apply(self, rule: Rule, action: str, text: str) -> str:
        def repl(m: re.Match[str]) -> str:
            found = m.group(0)
            if rule.luhn and not _luhn_ok(found):
                return found
            if action == "redact":
                self.redacted[rule.code] += 1
                self.n_redacted += 1
                return f"[REDACTED:{rule.code}]"
            if action == "flag":
                self.flagged[rule.code] += 1
            elif action == "block":
                self.blocked[rule.code] += 1
            return found

        return rule.pattern.sub(repl, text)

    def text(self, raw: str) -> str:
        self.budget -= len(raw)
        if self.budget < 0:
            raise TooLarge("result too large to inspect")
        if not raw:
            return raw
        view = clean(raw)  # strips zero-width tricks so "AK<ZWSP>IA..." is still caught
        before = self.n_redacted
        for rule, action in self.plan:
            view = self._apply(rule, action, view)
        # Only hand back the edited copy if we actually redacted something.
        return view if self.n_redacted > before else raw

    def walk(self, value: Any, parent: Any = None, key: str = "", depth: int = 0) -> Any:
        if depth > MAX_DEPTH:
            raise TooLarge("result nested too deeply to inspect")
        if isinstance(value, str):
            if _is_binary(parent, key):
                self.unscanned += 1
                return value
            return self.text(value)
        if isinstance(value, dict):
            return {
                (self.text(k) if isinstance(k, str) else k): self.walk(
                    v, value, str(k), depth + 1
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.walk(v, parent, key, depth + 1) for v in value]
        return value


def _allowed_for(settings: EgressSettings, tool: str | None) -> frozenset[str]:
    allowed: set[str] = set()
    for ex in settings.exceptions:
        if tool is not None and ex.tool == tool:
            allowed.update(ex.allow)
    return frozenset(allowed)


def _record(
    audit: AuditSink | None,
    *,
    server: str,
    session_id: str,
    pending: Pending,
    scan: _Scan,
    decision: Decision,
    risk: float,
    reasons: list[str],
    ms: int,
) -> None:
    if audit is None:
        return
    signals: list[Signal] = []
    for action, counter, sev in (
        ("redact", scan.redacted, Severity.MEDIUM),
        ("flag", scan.flagged, Severity.LOW),
        ("block", scan.blocked, Severity.HIGH),
    ):
        for code, n in sorted(counter.items()):
            signals.append(
                Signal(
                    detector="egress_filter",
                    code=f"{action}_{code}",
                    weight=1.0 if action == "block" else 0.0,
                    severity=sev,
                    evidence=f"{n} match(es)",  # NEVER the matched text
                    hard_deny=action == "block",
                )
            )
    ctx = ToolCallContext(
        call_id=uuid4().hex,
        session_id=session_id,
        ts=datetime.now(UTC),
        server=server,
        tool=f"{pending.tool or pending.method}[result]",
        signals=signals,
    )
    final = FinalDecision(
        decision=decision,
        risk=risk,
        reasons=reasons,
        redactions=[f"{c}x{n}" for c, n in sorted(scan.redacted.items())],
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
                latency_breakdown_ms={"egress": ms},
            )
        )
    except Exception as exc:  # noqa: BLE001
        log(f"egress audit write failed: {type(exc).__name__}")


def make_egress_hook(
    settings: EgressSettings,
    *,
    audit: AuditSink | None,
    server: str,
    session_id: str,
) -> ResponseHook:
    plan = build_plan(settings)

    async def hook(msg: dict[str, Any], pending: Pending) -> dict[str, Any] | None:
        if pending.method not in EGRESS_METHODS or not plan:
            return None
        t0 = time.perf_counter()
        scan = _Scan(plan, _allowed_for(settings, pending.tool), settings.max_scan_chars)
        too_big = False
        new: dict[str, Any] = msg
        try:
            new = {
                k: (scan.walk(v) if k in ("result", "error") else v) for k, v in msg.items()
            }
        except TooLarge:
            too_big = True
        ms = int((time.perf_counter() - t0) * 1000)
        label = pending.tool or pending.method

        if too_big or scan.blocked:
            why = "egress_filter/too_large" if too_big else (
                "egress_filter/" + ",".join(sorted(scan.blocked))
            )
            log(f"egress tool={label} BLOCKED reason={why} ms={ms}")
            _record(
                audit, server=server, session_id=session_id, pending=pending, scan=scan,
                decision=Decision.DENY, risk=1.0, reasons=[why], ms=ms,
            )
            make = (
                jsonrpc.blocked_response if pending.method == "tools/call" else jsonrpc.error_response
            )
            return make(msg.get("id"), why)

        if scan.redacted or scan.flagged:
            reasons = [f"egress_filter/redact {c} x{n}" for c, n in sorted(scan.redacted.items())]
            reasons += [f"egress_filter/flag {c} x{n}" for c, n in sorted(scan.flagged.items())]
            log(
                f"egress tool={label} redacted={dict(scan.redacted)} "
                f"flagged={dict(scan.flagged)} ms={ms}"
            )
            _record(
                audit, server=server, session_id=session_id, pending=pending, scan=scan,
                decision=Decision.REDACT if scan.redacted else Decision.ALLOW,
                risk=0.5 if scan.redacted else 0.2,  # display-only numbers
                reasons=reasons, ms=ms,
            )
        return new if scan.redacted else None

    return hook
