from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from zem.contracts.models import ToolCallContext


class MalformedCallError(ValueError):
    """The tools/call message is missing something a real call must have."""


def build_context(msg: dict[str, Any], *, server: str, session_id: str) -> ToolCallContext:
    params = msg.get("params")
    if not isinstance(params, dict):
        raise MalformedCallError("params missing or not an object")

    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise MalformedCallError("tool name missing")

    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise MalformedCallError("arguments is not an object")

    return ToolCallContext(
        call_id=uuid4().hex,
        session_id=session_id,
        ts=datetime.now(UTC),
        server=server,
        tool=name,
        arguments=arguments,
    )
