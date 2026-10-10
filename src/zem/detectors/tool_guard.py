from __future__ import annotations

from zem.contracts.models import Severity, Signal, ToolCallContext


class ToolGuard:
    """Per-tool allow/deny from the policy file."""

    name = "tool_guard"

    def __init__(self, allow: list[str] | None, deny: list[str]) -> None:
        self.allow = None if allow is None else set(allow)
        self.deny = set(deny)

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        if ctx.tool in self.deny:
            code = "tool_denied"
        elif self.allow is not None and ctx.tool not in self.allow:
            code = "tool_not_allowed"
        else:
            return []
        return [
            Signal(
                detector=self.name,
                code=code,
                weight=1.0,
                severity=Severity.HIGH,
                evidence=f"tool={ctx.tool!r}",
                hard_deny=True,
            )
        ]
