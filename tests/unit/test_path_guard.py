from datetime import UTC, datetime

import pytest

from zem.contracts.models import ToolCallContext
from zem.detectors.path_guard import PathGuard

GUARD = PathGuard(["/workspace"])


def ctx(args: dict) -> ToolCallContext:
    return ToolCallContext(
        call_id="c",
        session_id="s",
        ts=datetime.now(UTC),
        server="fs",
        tool="read_file",
        arguments=args,
    )


def denied(args: dict) -> bool:
    return any(s.hard_deny for s in GUARD.inspect(ctx(args)))


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "%252e%252e%252f%252e%252e%252fetc/passwd",  # double-encoded
        "..\\..\\windows\\win.ini",
        "src/../../secret",
        "~/.ssh/id_rsa",
        "/workspace-evil/x",  # prefix trick
        "file.txt\x00.png",  # null byte
    ],
)
def test_bad_paths_denied(bad):
    assert denied({"path": bad})


@pytest.mark.parametrize(
    "good",
    [
        "src/main.py",
        "./README.md",
        "/workspace/src/a.py",
        "src/../README.md",  # goes up, but stays inside /workspace
        "docs/notes.txt",
    ],
)
def test_good_paths_allowed(good):
    assert not denied({"path": good})


def test_nested_and_weird_inputs():
    assert denied({"files": ["ok.txt", "../../x"]})  # inside a list
    assert denied({"opts": {"target": "a/../../b"}})  # inside a dict
    assert not denied({})  # no arguments
    assert not denied({"count": 5, "flag": True, "x": None})  # no strings
    assert not denied({"text": "hello /approve this"})  # prose, not a path
    assert not denied({"path": "a" * 100_000})  # huge but harmless
