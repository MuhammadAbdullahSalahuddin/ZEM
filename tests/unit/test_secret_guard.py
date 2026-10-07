from datetime import UTC, datetime

import pytest

from zem.contracts.models import ToolCallContext
from zem.detectors.secret_guard import SecretGuard

GUARD = SecretGuard()

AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB = "ghp_" + "a" * 36
PRIVATE = "-----BEGIN " + "RSA PRIVATE KEY-----"
JWT = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTYifQ" + "." + "abcdefghij12345"


def run(args: dict):
    ctx = ToolCallContext(
        call_id="c",
        session_id="s",
        ts=datetime.now(UTC),
        server="gh",
        tool="create_comment",
        arguments=args,
    )
    return GUARD.inspect(ctx)


@pytest.mark.parametrize("secret", [AWS, GITHUB, PRIVATE])
def test_hard_secrets_denied(secret):
    signals = run({"body": f"here you go: {secret}"})
    assert any(s.hard_deny for s in signals)


def test_evidence_never_contains_the_secret():
    signals = run({"body": AWS})
    assert signals and all(AWS not in s.evidence for s in signals)


def test_jwt_is_soft_signal():
    signals = run({"header": JWT})
    assert signals and not any(s.hard_deny for s in signals)


def test_clean_and_weird_inputs():
    assert run({"body": "fix the login bug"}) == []
    assert run({}) == []
    assert run({"n": 3, "deep": {"x": ["AKIA-not-a-key"]}}) == []  # looks close, isn't one
    assert run({"body": "x" * 200_000}) == []
