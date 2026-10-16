from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import uuid4

from zem.contracts.models import (
    AuditEvent,
    AuditSink,
    Decision,
    Detector,
    FinalDecision,
    Reasoner,
    Severity,
    Signal,
    ToolCallContext,
)
from zem.pipeline.judge_stage import JudgeBudget, decide_gray, summarize_call
from zem.pipeline.normalizer import MalformedCallError, build_context
from zem.policy.loader import Policy
from zem.protocol import jsonrpc
from zem.protocol.stdio_proxy import Interceptor, log


class Pipeline:
    def __init__(self, detectors: Sequence[Detector], hard_codes: Iterable[str] = ()) -> None:
        self.detectors = list(detectors)
        self.hard_codes = frozenset(hard_codes)

    def evaluate(self, ctx: ToolCallContext) -> FinalDecision:
        signals: list[Signal] = []
        for detector in self.detectors:
            try:
                signals.extend(detector.inspect(ctx))
            except Exception as exc:  # noqa: BLE001 (fail CLOSED: a crashing detector means deny)
                signals.append(
                    Signal(
                        detector=detector.name,
                        code="detector_crashed",
                        weight=1.0,
                        severity=Severity.CRITICAL,
                        evidence=type(exc).__name__,
                        hard_deny=True,
                    )
                )
        ctx.signals = signals

        risk = max((s.weight for s in signals), default=0.0)  # R2 replaces this
        hard = [s for s in signals if s.hard_deny or s.code in self.hard_codes]
        if hard:
            reasons = [f"{s.detector}/{s.code} ({s.evidence})" for s in hard]
            return FinalDecision(decision=Decision.DENY, risk=risk, reasons=reasons)
        return FinalDecision(decision=Decision.ALLOW, risk=risk)

def make_interceptor(
    pipeline: Pipeline,
    *,
    server: str,
    session_id: str | None = None,
    audit: AuditSink | None = None,
    reasoner: Reasoner | None = None,
    policy: Policy | None = None,
) -> Interceptor:
    sid = session_id or uuid4().hex
    r2 = policy is not None and policy.judge.enabled
    budget = (
        JudgeBudget(policy.budgets.max_judge_per_session, policy.budgets.max_judge_global)
        if policy is not None
        else JudgeBudget(0, 0)
    )
    history: deque[dict[str, Any]] = deque(maxlen=5)

    async def interceptor(msg: dict[str, Any]) -> dict[str, Any] | None:
        t0 = time.perf_counter()
        try:
            ctx = build_context(msg, server=server, session_id=sid)
        except MalformedCallError as exc:
            log(f"deny malformed tools/call: {exc}")
            return jsonrpc.blocked_response(msg.get("id"), f"malformed tools/call ({exc})")

        final = pipeline.evaluate(ctx)  # R1: detectors + hard denies
        detector_ms = int((time.perf_counter() - t0) * 1000)

        verdict = None
        judge_ms = 0
        if r2 and policy is not None and final.decision is Decision.ALLOW:
            final, verdict, judge_ms = await decide_gray(
                ctx, policy=policy, reasoner=reasoner, budget=budget, history=history
            )
        history.append(summarize_call(ctx, final))

        micros = int((time.perf_counter() - t0) * 1_000_000)
        log(
            f"{final.decision.value} tool={ctx.tool} risk={final.risk:.2f} "
            f"reasons={'; '.join(final.reasons) or '-'} latency_us={micros}"
        )
        if audit is not None:
            try:
                audit.append(
                    AuditEvent(
                        seq=0,
                        ts=ctx.ts,
                        session_id=sid,
                        call_id=ctx.call_id,
                        context=ctx,
                        judge=verdict,
                        final=final,
                        latency_breakdown_ms={"pipeline": detector_ms, "judge": judge_ms},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                log(f"audit write failed: {type(exc).__name__}")
        if final.decision is not Decision.ALLOW:  # was "is DENY": other decisions leaked through
            return jsonrpc.blocked_response(msg.get("id"), "; ".join(final.reasons))
        return None

    return interceptor
