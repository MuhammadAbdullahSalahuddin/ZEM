from __future__ import annotations

import re

from zem.contracts.models import Severity, Signal, ToolCallContext
from zem.detectors._util import iter_strings

# (code, pattern, weight, hard_deny)
PATTERNS: list[tuple[str, re.Pattern[str], float, bool]] = [
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0.95, True),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
        0.95,
        True,
    ),
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"), 0.99, True),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        0.5,
        False,
    ),
]


class SecretGuard:
    name = "secret_guard"

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        signals: list[Signal] = []
        for key, text in iter_strings(ctx.arguments):
            for code, pattern, weight, hard in PATTERNS:
                match = pattern.search(text)
                if match is None:
                    continue
                found = match.group(0)
                signals.append(
                    Signal(
                        detector=self.name,
                        code=code,
                        weight=weight,
                        severity=Severity.HIGH if hard else Severity.MEDIUM,
                        # Masked on purpose: never write the secret into our own logs.
                        evidence=f"{key}: {found[:4]}...({len(found)} chars)",
                        hard_deny=hard,
                    )
                )
        return signals
