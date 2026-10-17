from __future__ import annotations

import re

from zem.contracts.models import Severity, Signal, ToolCallContext
from zem.detectors._util import iter_strings

SEND_WORDS = frozenset(
    {"send", "post", "upload", "publish", "email", "mail", "webhook", "comment",
     "notify", "push", "share", "forward"}
)
MIN_CHARS = 500  # a short "ok thanks" is not data leaving; 500+ characters might be


def _words(tool: str) -> set[str]:
    return {w.lower() for w in re.split(r"[_\-.\s]+|(?<=[a-z])(?=[A-Z])", tool) if w}


class OutboundGuard:
    name = "outbound_guard"

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        if not (_words(ctx.tool) & SEND_WORDS):
            return []
        biggest = max((len(t) for _k, t in iter_strings(ctx.arguments)), default=0)
        if biggest < MIN_CHARS:
            return []
        return [Signal(
            detector=self.name, code="outbound_with_data", weight=0.4,
            severity=Severity.MEDIUM,
            evidence=f"{ctx.tool}: {biggest} chars of data leaving",
        )]
