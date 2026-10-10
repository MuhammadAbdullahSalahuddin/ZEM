from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import uuid4

from zem.contracts.models import (
    AuditEvent,
    AuditSink,
    Decision,
    Detector,
    FinalDecision,
    Severity,
    Signal,
    ToolCallContext,
)
from zem.pipeline.normalizer import MalformedCallError, build_context
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
) -> Interceptor:
    sid = session_id or uuid4().hex

    async def interceptor(msg: dict[str, Any]) -> dict[str, Any] | None:
        t0 = time.perf_counter()
        try:
            ctx = build_context(msg, server=server, session_id=sid)
        except MalformedCallError as exc:
            log(f"deny malformed tools/call: {exc}")
            return jsonrpc.blocked_response(msg.get("id"), f"malformed tools/call ({exc})")

        final = pipeline.evaluate(ctx)
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
                        final=final,
                        latency_breakdown_ms={"pipeline": micros // 1000},
                    )
                )
            except Exception as exc:  # noqa: BLE001 (a broken log must not break the decision)
                log(f"audit write failed: {type(exc).__name__}")
        if final.decision is Decision.DENY:
            return jsonrpc.blocked_response(msg.get("id"), "; ".join(final.reasons))
        return None

    return interceptor
