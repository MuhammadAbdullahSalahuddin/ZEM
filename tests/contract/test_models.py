from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from zem.contracts.models import (
    AuditEvent,
    Decision,
    FinalDecision,
    Signal,
    ToolCallContext,
    ToolResultContext,
)


def _ctx() -> ToolCallContext:
    return ToolCallContext(
        call_id="c1",
        session_id="s1",
        ts=datetime.now(UTC),
        server="echo",
        tool="echo",
        arguments={"text": "hi"},
    )


def test_context_defaults():
    ctx = _ctx()
    assert ctx.signals == []
    assert ctx.objective is None


def test_signal_weight_bounds():
    Signal(detector="d", code="c", weight=0.5, evidence="e")
    with pytest.raises(ValidationError):
        Signal(detector="d", code="c", weight=1.5, evidence="e")


def test_audit_event_roundtrip():
    ev = AuditEvent(
        seq=1,
        ts=datetime.now(UTC),
        session_id="s1",
        call_id="c1",
        context=_ctx(),
        final=FinalDecision(decision=Decision.ALLOW, risk=0.0),
    )
    assert AuditEvent.model_validate_json(ev.model_dump_json()) == ev


def test_result_context():
    r = ToolResultContext(call_id="c1", session_id="s1", server="echo", tool="echo")
    assert r.is_error is False
