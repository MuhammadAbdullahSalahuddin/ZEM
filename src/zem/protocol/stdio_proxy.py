from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from zem.protocol import jsonrpc

# Given a tools/call message, return a reply dict to answer it ourselves
# (block), or None to forward it to the real tool.
Interceptor = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]

MAX_LINE = 16 * 1024 * 1024  # 16 MB per JSON line


def log(msg: str) -> None:
    # stderr ONLY. stdout is the MCP channel; stray text there corrupts it.
    print(f"[zem] {msg}", file=sys.stderr, flush=True)


async def logging_interceptor(msg: dict[str, Any]) -> dict[str, Any] | None:
    params = msg.get("params") or {}
    log(f"tools/call id={msg.get('id')} tool={params.get('name')}")
    return None  # R0: forward everything


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


async def _agent_to_child(
    queue: asyncio.Queue[bytes],
    child: asyncio.subprocess.Process,
    interceptor: Interceptor,
) -> None:
    assert child.stdin is not None
    while True:
        line = await queue.get()
        if not line:
            break
        msg = jsonrpc.parse_line(line)
        if msg is not None and jsonrpc.is_tool_call(msg):
            reply = await interceptor(msg)
            if reply is not None:
                _write_stdout(jsonrpc.dumps(reply))
                continue
        child.stdin.write(line if line.endswith(b"\n") else line + b"\n")
        await child.stdin.drain()
    child.stdin.close()


async def _child_to_agent(child: asyncio.subprocess.Process) -> None:
    assert child.stdout is not None
    while True:
        line = await child.stdout.readline()
        if not line:
            break
        _write_stdout(line)


async def run_proxy(cmd: list[str], interceptor: Interceptor | None = None) -> int:
    interceptor = interceptor or logging_interceptor
    child = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,  # child's stderr flows to our stderr
        limit=MAX_LINE,
    )
    queue: asyncio.Queue[bytes] = asyncio.Queue()
    _start_stdin_reader(asyncio.get_running_loop(), queue)

    t_in = asyncio.create_task(_agent_to_child(queue, child, interceptor))
    t_out = asyncio.create_task(_child_to_agent(child))
    try:
        await t_out  # child closed stdout: we are done
    finally:
        t_in.cancel()
        if child.returncode is None:
            child.terminate()
        await child.wait()
    return child.returncode or 0
