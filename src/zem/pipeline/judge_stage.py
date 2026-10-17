from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from typing import Any

from zem.contracts.models import (
    Decision,
    FinalDecision,
    JudgeVerdict,
    Reasoner,
    Severity,
    Signal,
    ToolCallContext,
)
from zem.detectors.secret_guard import PATTERNS
from zem.pipeline.scoring import Route, noisy_or, route
from zem.policy.loader import Policy
from zem.protocol.stdio_proxy import log

MAX_JUDGE_STR = 2000
# snake_case or camelCase tools that only look: read_file, getIssue, list_dir ...
READ_ONLY = re.compile(r"^(read|get|list|search|find|describe|show|cat|stat|view|head|tail)(_|$|[A-Z])")


def mask_for_judge(value: Any) -> Any:
    """Copy with secrets masked and long strings cut. Mask BEFORE cutting."""
    if isinstance(value, str):
        for code, pattern, _w, _h in PATTERNS:
            value = pattern.sub(f"[REDACTED:{code}]", value)
        return value[:MAX_JUDGE_STR]
    if isinstance(value, dict):
        return {k: mask_for_judge(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_for_judge(v) for v in value]
    return value


def summarize_call(ctx: ToolCallContext, final: FinalDecision) -> dict[str, Any]:
    args = json.dumps(mask_for_judge(ctx.arguments), default=str)[:200]
    return {"tool": ctx.tool, "decision": final.decision.value, "args": args}


class JudgeBudget:
    """Caps model calls. Per process: one `zem wrap` = one session (see risks below)."""

    def __init__(self, per_session: int, total: int) -> None:
        self.per_session, self.total = per_session, total
        self.used = 0
        self.by_session: dict[str, int] = {}

    def take(self, session_id: str) -> bool:
        if self.used >= self.total or self.by_session.get(session_id, 0) >= self.per_session:
            return False
        self.used += 1
        self.by_session[session_id] = self.by_session.get(session_id, 0) + 1
        return True


async def ask_judge(ctx: ToolCallContext, reasoner: Reasoner, timeout_s: float) -> JudgeVerdict:
    safe = ctx.model_copy(update={"arguments": mask_for_judge(ctx.arguments)})
    return await asyncio.wait_for(reasoner.judge(safe, depth="fast"), timeout=timeout_s)


def fallback_allows(policy: Policy, tool: str) -> bool:
    if policy.on_error == "fail_open":
        return True
    if policy.on_error == "fail_closed":
        return False
    return tool in policy.read_only_tools or bool(READ_ONLY.match(tool))


def _fallback(
    ctx: ToolCallContext, policy: Policy, risk: float, why: str, detail: str = ""
) -> FinalDecision:
    """No usable verdict: decide from policy.on_error and leave a trace in the signals."""
    ctx.signals.append(
        Signal(
            detector="router",
            code=why,
            weight=0.0,
            severity=Severity.INFO,
            evidence=detail or why,
        )
    )
    if fallback_allows(policy, ctx.tool):
        log(f"ALERT no judge verdict ({why}); fail-open for read-only tool {ctx.tool}")
        return FinalDecision(
            decision=Decision.ALLOW, risk=risk, reasons=[f"router/{why} (fail-open)"]
        )
    return FinalDecision(
        decision=Decision.DENY, risk=risk, reasons=[f"router/{why} (fail-closed)"]
    )


async def decide_gray(
    ctx: ToolCallContext,
    *,
    policy: Policy,
    reasoner: Reasoner | None,
    budget: JudgeBudget,
    history: deque[dict[str, Any]],
) -> tuple[FinalDecision, JudgeVerdict | None, int]:
    """Soft-signal stage. Only called when no detector hard-denied."""
    risk = noisy_or(s.weight for s in ctx.signals)
    where = route(risk, policy.thresholds, deep_enabled=policy.judge.deep_enabled)
    top = ", ".join(
        f"{s.detector}/{s.code}" for s in sorted(ctx.signals, key=lambda s: -s.weight)[:3]
    ) or "-"

    if where is Route.ALLOW:
        return FinalDecision(decision=Decision.ALLOW, risk=risk), None, 0
    if where is Route.DENY:
        reason = f"router/risk {risk:.2f} ({top})"
        return FinalDecision(decision=Decision.DENY, risk=risk, reasons=[reason]), None, 0

    if reasoner is None:
        return _fallback(ctx, policy, risk, "no_reasoner"), None, 0
    if not budget.take(ctx.session_id):
        return _fallback(ctx, policy, risk, "budget_exhausted"), None, 0

    t0 = time.perf_counter()
    ctx.recent_calls = list(history)
    try:
        verdict = await ask_judge(ctx, reasoner, policy.judge.timeout_s)
    except Exception as exc:  # noqa: BLE001 (timeout, crash, bad output)
        ms = int((time.perf_counter() - t0) * 1000)
        return _fallback(ctx, policy, risk, "judge_unavailable", type(exc).__name__), None, ms
    ms = int((time.perf_counter() - t0) * 1000)

    sure = verdict.confidence >= policy.judge.min_confidence
    if sure and verdict.verdict == "allow":
        reason = f"judge/allow ({verdict.reason[:200]})"
        return FinalDecision(decision=Decision.ALLOW, risk=risk, reasons=[reason]), verdict, ms
    if sure and verdict.verdict == "deny":
        reason = f"judge/deny ({verdict.reason[:200]})"
        final = FinalDecision(
            decision=Decision.DENY, risk=max(risk, verdict.confidence), reasons=[reason]
        )
        return final, verdict, ms
    return _fallback(ctx, policy, risk, "judge_unsure", verdict.verdict), verdict, ms
