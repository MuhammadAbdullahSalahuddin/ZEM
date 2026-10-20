import json
from collections import OrderedDict

from zem.protocol import jsonrpc
from zem.protocol.stdio_proxy import (
    MAX_PENDING,
    Pending,
    _remember,
    _screen_line,
    _screen_request,
)


def line(obj) -> bytes:
    return (json.dumps(obj) + "\n").encode()


def call(i, tool="read_file"):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": tool, "arguments": {}}}


def answer(i, text="hello"):
    return {"jsonrpc": "2.0", "id": i, "result": {"content": [{"type": "text", "text": text}]}}


async def allow(msg):
    return None


async def deny(msg):
    return jsonrpc.blocked_response(msg.get("id"), "no")


class Spy:
    def __init__(self, replace=None, boom=False):
        self.seen, self.replace, self.boom = [], replace, boom

    async def __call__(self, msg, pending):
        self.seen.append(pending)
        if self.boom:
            raise RuntimeError("x")
        return self.replace


# ---- request side (agent -> tool) ----

async def test_allowed_call_is_remembered_and_forwarded():
    nb = OrderedDict()
    forward, reply = await _screen_request(line(call(7)), nb, allow)
    assert reply is None and forward == line(call(7))
    assert nb[7] == Pending("tools/call", "read_file")


async def test_blocked_call_is_answered_and_not_remembered():
    nb = OrderedDict()
    forward, reply = await _screen_request(line(call(7)), nb, deny)
    assert forward is None and reply["id"] == 7 and reply["result"]["isError"] is True
    assert nb == {}


async def test_batch_is_rejected_not_forwarded():
    nb = OrderedDict()
    forward, reply = await _screen_request(line([call(1), call(2)]), nb, allow)
    assert forward is None and reply["error"]["code"] == -32600


async def test_garbage_and_blank_lines():
    nb = OrderedDict()
    forward, reply = await _screen_request(b"not json\n", nb, allow)
    assert forward is None and "error" in reply
    assert await _screen_request(b"\n", nb, allow) == (None, None)


def test_remember_survives_weird_input():
    nb = OrderedDict()
    for bad in (
        {"method": [], "id": 1},
        {"method": {"a": 1}, "id": 2},
        {"method": "tools/call", "id": True},
        {"method": "tools/call", "id": [1]},
        {"method": "tools/call"},
        {"method": "ping", "id": 3},
    ):
        _remember(nb, bad)
    assert nb == {}


def test_notebook_is_capped_and_forgets_the_oldest():
    nb = OrderedDict()
    for i in range(MAX_PENDING + 5):
        _remember(nb, call(i))
    assert len(nb) == MAX_PENDING and 0 not in nb and MAX_PENDING + 4 in nb


# ---- answer side (tool -> agent) ----

async def test_answer_reaches_hook_and_original_bytes_survive():
    nb = OrderedDict({7: Pending("tools/call", "read_file")})
    spy = Spy()
    raw = b'{"jsonrpc": "2.0",  "id": 7, "result": {"content": []}}\n'
    assert await _screen_line(raw, nb, spy) == raw  # untouched, byte for byte
    assert spy.seen == [Pending("tools/call", "read_file")]
    assert 7 not in nb  # crossed off


async def test_hook_can_replace_the_answer():
    nb = OrderedDict({7: Pending("tools/call", "read_file")})
    out = await _screen_line(line(answer(7, "secret")), nb, Spy(replace=answer(7, "[REDACTED]")))
    assert json.loads(out)["result"]["content"][0]["text"] == "[REDACTED]"


async def test_tools_list_answer_is_tracked_too():
    nb = OrderedDict({8: Pending("tools/list")})
    spy = Spy()
    await _screen_line(line({"jsonrpc": "2.0", "id": 8, "result": {"tools": []}}), nb, spy)
    assert spy.seen == [Pending("tools/list")]


async def test_crashing_hook_fails_closed():
    nb = OrderedDict({5: Pending("tools/call", "x"), 6: Pending("tools/list")})
    out = json.loads(await _screen_line(line(answer(5)), nb, Spy(boom=True)))
    assert out["id"] == 5 and out["result"]["isError"] is True
    out = json.loads(await _screen_line(line(answer(6)), nb, Spy(boom=True)))
    assert out["id"] == 6 and "error" in out and "result" not in out


async def test_server_requests_and_untracked_answers_pass_through():
    spy = Spy()
    nb = OrderedDict()
    req = line({"jsonrpc": "2.0", "id": 99, "method": "sampling/createMessage"})
    assert await _screen_line(req, nb, spy) == req
    note = line({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
    assert await _screen_line(note, nb, spy) == note
    untracked = line(answer(42))
    assert await _screen_line(untracked, nb, spy) == untracked
    assert spy.seen == []


async def test_junk_from_the_tool_is_dropped():
    nb = OrderedDict()
    assert await _screen_line(b"debug: AKIA...\n", nb, Spy()) is None
    assert await _screen_line(line({"jsonrpc": "2.0"}), nb, Spy()) is None
    assert await _screen_line(b"\n", nb, Spy()) is None
