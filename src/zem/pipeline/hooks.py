from __future__ import annotations

from typing import Any

from zem.protocol.stdio_proxy import Pending, ResponseHook


def chain_hooks(*hooks: ResponseHook) -> ResponseHook:
    """Run hooks in order; each sees the previous one's output. None if nobody changed anything."""

    async def hook(msg: dict[str, Any], pending: Pending) -> dict[str, Any] | None:
        current, changed = msg, False
        for h in hooks:
            out = await h(current, pending)
            if out is not None:
                current, changed = out, True
        return current if changed else None

    return hook
