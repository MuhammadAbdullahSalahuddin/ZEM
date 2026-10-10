from datetime import UTC, datetime

import pytest

from zem.contracts.models import ToolCallContext
from zem.detectors.net_guard import NetGuard


def run(guard, args):
    ctx = ToolCallContext(
        call_id="c", session_id="s", ts=datetime.now(UTC), server="x", tool="fetch", arguments=args
    )
    return guard.inspect(ctx)


G = NetGuard(["github.com"])


@pytest.mark.parametrize(
    "bad",
    [
        "curl http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/x",
        "http://2852039166/",  # decimal form of 169.254.169.254
        "https://evil.com/x",
        "https://github.com.evil.com/x",  # suffix trick
        "http://github.com@evil.com/",  # userinfo trick
        "http://[::1",  # malformed
    ],
)
def test_bad_denied(bad):
    assert any(s.hard_deny for s in run(G, {"url": bad}))


@pytest.mark.parametrize(
    "good",
    [
        "https://github.com/a/b",
        "https://api.github.com/repos/x",
        "no urls here",
    ],
)
def test_good_allowed(good):
    assert run(G, {"url": good}) == []


def test_weird_inputs():
    assert run(G, {}) == []
    assert run(G, {"x": "a" * 200_000}) == []
    assert run(NetGuard([]), {"u": "https://anything.org"}) == []  # empty allowlist
    assert run(NetGuard([]), {"u": "http://10.0.0.5/"})  # IP still blocked
