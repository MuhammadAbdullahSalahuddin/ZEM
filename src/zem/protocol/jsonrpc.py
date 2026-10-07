from __future__ import annotations

import json
from typing import Any


def parse_line(line: bytes | str) -> dict[str, Any] | None:
    """Parse one JSON-RPC line. Returns None if it isn't a JSON object."""
    try:
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        obj = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def dumps(msg: dict[str, Any]) -> bytes:
    """Serialize to one compact line, newline-terminated."""
    return json.dumps(msg, separators=(",", ":")).encode("utf-8") + b"\n"


def is_tool_call(msg: dict[str, Any]) -> bool:
    return msg.get("method") == "tools/call"


def blocked_response(request_id: Any, reason: str) -> dict[str, Any]:
    """A tools/call result the agent can read and understand.

    isError=True makes the agent see the reason as a tool failure.
    [VERIFY against the current MCP spec revision.]
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": f"Blocked by ZEM policy: {reason}"}],
            "isError": True,
        },
    }
