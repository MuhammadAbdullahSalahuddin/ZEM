"""Pin guard detector (R3-I2): hard-denies calls to tools the response hook has quarantined."""

from __future__ import annotations

import re

from zem.contracts.models import Severity, Signal, ToolCallContext

_UNSAFE = re.compile(r"[^\w.\-:/ ]")


def safe_name(name: object, limit: int = 64) -> str:
    """Tool names come from the (untrusted) server. Neutralise anything that could confuse a
    terminal (escape codes) or a dashboard (HTML) before it reaches a log, a row or a screen."""
    text = name if isinstance(name, str) else repr(name)
    return _UNSAFE.sub("?", text)[:limit]


class PinState:
    """Tools this session must not call: written by the response hook, read by PinGuard."""

    def __init__(self, quarantined: dict[str, str] | None = None) -> None:
        self.quarantined: dict[str, str] = dict(quarantined or {})


class PinGuard:
    name = "pin_guard"

    def __init__(self, state: PinState) -> None:
        self.state = state

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        reason = self.state.quarantined.get(ctx.tool)
        if reason is None:
            return []
        return [
            Signal(
                detector=self.name,
                code="tool_quarantined",
                weight=1.0,
                severity=Severity.HIGH,
                evidence=f"tool={safe_name(ctx.tool)!r}: {safe_name(reason, 80)}",
                hard_deny=True,
            )
        ]
