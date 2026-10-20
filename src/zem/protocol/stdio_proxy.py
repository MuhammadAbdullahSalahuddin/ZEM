from __future__ import annotations

import asyncio
import sys
import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from zem.protocol import jsonrpc

# Given a tools/call message, return a reply dict to answer it ourselves
# (block), or None to forward it to the real tool.
Interceptor = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]

MAX_LINE = 16 * 1024 * 1024  # 16 MB per JSON line
MAX_PENDING = 10_000  # requests we are still waiting on answers for
# Requests whose ANSWERS we want to inspect (they carry content from the tool).
TRACKED_METHODS = frozenset({"tools/call", "tools/list", "resources/read", "prompts/get"})


@dataclass(frozen=True)
class Pending:
    """What we remember about a forwarded request, so we can recognise its answer."""

    method: str
    tool: str | None = None


# Given an answer and what it answers, return a replacement message, or None to keep it.
ResponseHook = Callable[[dict[str, Any], Pending], Awaitable[dict[str, Any] | None]]
Notebook = OrderedDict[Any, Pending]


def log(msg: str) -> None:
    # stderr ONLY. stdout is the MCP channel; stray text there corrupts it.
    print(f"[zem] {msg}", file=sys.stderr, flush=True)


async def logging_interceptor(msg: dict[str, Any]) -> dict[str, Any] | None:
    params = msg.get("params") or {}
    log(f"tools/call id={msg.get('id')} tool={params.get('name')}")
    return None  # R0: forward everything


async def logging_response_hook(msg: dict[str, Any], pending: Pending) -> dict[str, Any] | None:
    # Never log the content of an answer: it may hold the very secrets we are guarding.
    log(f"result id={msg.get('id')} method={pending.method} tool={pending.tool}")
    return None


def _write_stdout(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _start_stdin_reader(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[bytes]) -> None:
    def reader() -> None:
        while True:
            line = sys.stdin.buffer.readline()
            loop.call_soon_threadsafe(queue.put_nowait, line)
            if not line:  # EOF
                break

    threading.Thread(target=reader, daemon=True).start()


def _valid_id(value: Any) -> bool:
    # JSON-RPC ids are strings or integers. bool is an int in Python, so exclude it.
    return isinstance(value, int | str) and not isinstance(value, bool)


def _remember(notebook: Notebook, msg: dict[str, Any]) -> None:
    method = msg.get("method")
    if not isinstance(method, str) or method not in TRACKED_METHODS:
        return
    rid = msg.get("id")
    if not _valid_id(rid):
        return
    params = msg.get("params")
    tool = params.get("name") if method == "tools/call" and isinstance(params, dict) else None
    if len(notebook) >= MAX_PENDING:
        notebook.popitem(last=False)  # forget the oldest
    notebook[rid] = Pending(method, tool if isinstance(tool, str) else None)


async def _screen_request(
    line: bytes, notebook: Notebook, interceptor: Interceptor
) -> tuple[bytes | None, dict[str, Any] | None]:
    """Decide what to do with one line from the agent.

    Returns (bytes to forward to the tool, reply to send straight back to the agent).
    At most one of the two is set. Both None means: ignore the line.
    """
    if not line.strip():
        return None, None
    msg = jsonrpc.parse_line(line)
    if msg is None:  # fail CLOSED: not a single JSON object, so we cannot inspect it
        why = (
            "batch requests are not supported"
            if line.lstrip().startswith(b"[")
            else "request is not valid JSON"
        )
        return None, jsonrpc.error_response(None, why, code=-32600)
    if jsonrpc.is_tool_call(msg):
        reply = await interceptor(msg)
        if reply is not None:
            return None, reply
    _remember(notebook, msg)
    return (line if line.endswith(b"\n") else line + b"\n"), None


async def _screen_line(line: bytes, notebook: Notebook, hook: ResponseHook) -> bytes | None:
    """Decide what to send to the agent for one line from the tool. None means: send nothing."""
    if not line.strip():
        return None
    msg = jsonrpc.parse_line(line)
    if msg is None:
        log("dropped a non-JSON line from the tool server")
        return None
    raw = line if line.endswith(b"\n") else line + b"\n"
    if "method" in msg:  # a notification or a request FROM the server: not an answer
        return raw
    if not jsonrpc.is_response(msg):
        log("dropped a malformed message from the tool server")
        return None
    rid = msg["id"]
    pending = notebook.pop(rid, None) if _valid_id(rid) else None
    if pending is None:  # an answer to something we do not track (initialize, ping...)
        return raw
    try:
        replacement = await hook(msg, pending)
    except Exception as exc:  # noqa: BLE001 (fail CLOSED: never pass an uninspected result)
        log(f"result inspection crashed ({type(exc).__name__}); blocking this result")
        make = jsonrpc.blocked_response if pending.method == "tools/call" else jsonrpc.error_response
        replacement = make(rid, "could not inspect this result")
    return raw if replacement is None else jsonrpc.dumps(replacement)


async def _agent_to_child(
    queue: asyncio.Queue[bytes],
    child: asyncio.subprocess.Process,
    interceptor: Interceptor,
    notebook: Notebook,
) -> None:
    assert child.stdin is not None
    while True:
        line = await queue.get()
        if not line:
            break
        forward, reply = await _screen_request(line, notebook, interceptor)
        if reply is not None:
            _write_stdout(jsonrpc.dumps(reply))
        if forward is not None:
            child.stdin.write(forward)
            await child.stdin.drain()
    child.stdin.close()


async def _child_to_agent(
    child: asyncio.subprocess.Process, notebook: Notebook, hook: ResponseHook
) -> None:
    assert child.stdout is not None
    while True:
        line = await child.stdout.readline()
        if not line:
            break
        out = await _screen_line(line, notebook, hook)
        if out is not None:
            _write_stdout(out)


async def run_proxy(
    cmd: list[str],
    interceptor: Interceptor | None = None,
    response_hook: ResponseHook | None = None,
) -> int:
    interceptor = interceptor or logging_interceptor
    hook = response_hook or logging_response_hook
    child = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,  # child's stderr flows to our stderr
        limit=MAX_LINE,
    )
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    _start_stdin_reader(asyncio.get_running_loop(), queue)
    notebook: Notebook = OrderedDict()

    t_in = asyncio.create_task(_agent_to_child(queue, child, interceptor, notebook))
    t_out = asyncio.create_task(_child_to_agent(child, notebook, hook))
    try:
        await t_out  # child closed stdout: we are done
    finally:
        t_in.cancel()
        if child.returncode is None:
            child.terminate()
        await child.wait()
    return child.returncode or 0
