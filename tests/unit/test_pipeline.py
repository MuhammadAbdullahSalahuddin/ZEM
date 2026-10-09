from datetime import UTC, datetime

from zem.contracts.models import Decision, Signal, ToolCallContext
from zem.detectors.path_guard import PathGuard
from zem.detectors.secret_guard import SecretGuard
from zem.pipeline.orchestrator import Pipeline, make_interceptor


def ctx(args: dict) -> ToolCallContext:
    return ToolCallContext(
        call_id="c",
        session_id="s",
        ts=datetime.now(UTC),
        server="fs",
        tool="read_file",
        arguments=args,
    )


class Crasher:
    name = "crasher"

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        raise RuntimeError("boom")


def test_attack_denied_benign_allowed():
    p = Pipeline([PathGuard(["/workspace"]), SecretGuard()])
    assert p.evaluate(ctx({"path": "../../etc/passwd"})).decision is Decision.DENY
    assert p.evaluate(ctx({"path": "src/a.py"})).decision is Decision.ALLOW


def test_crashing_detector_fails_closed():
    final = Pipeline([Crasher()]).evaluate(ctx({}))
    assert final.decision is Decision.DENY


async def test_interceptor_blocks_and_forwards():
    interceptor = make_interceptor(Pipeline([PathGuard(["/workspace"])]), server="fs")
    bad = {
        "id": 5,
        "method": "tools/call",
        "params": {"name": "read_file", "arguments": {"path": "/etc/passwd"}},
    }
    good = {
        "id": 6,
        "method": "tools/call",
        "params": {"name": "read_file", "arguments": {"path": "a.txt"}},
    }
    reply = await interceptor(bad)
    assert reply is not None and reply["id"] == 5 and reply["result"]["isError"] is True
    assert await interceptor(good) is None


async def test_malformed_call_is_blocked():
    interceptor = make_interceptor(Pipeline([]), server="fs")
    reply = await interceptor({"id": 9, "method": "tools/call", "params": {}})
    assert reply is not None and reply["result"]["isError"] is True
