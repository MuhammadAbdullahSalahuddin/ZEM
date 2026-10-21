import json
import os
import subprocess
import sys

WRAP = [sys.executable, "-c", "from zem.cli.main import app; app()"]
SERVER = [sys.executable, "demo/servers/rugpull_server.py"]


def _send(p, obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def _recv(p):
    line = p.stdout.readline()
    assert line, "proxy closed stdout unexpectedly"
    return json.loads(line)


def _open(db, **env):
    cmd = [*WRAP, "wrap", "--root", "/workspace", "--server-name", "rug", "--db", db, "--", *SERVER]
    p = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env={**os.environ, **env},
    )
    _send(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"}}})
    assert _recv(p)["id"] == 1
    _send(p, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return p


def _names(p, rid):
    _send(p, {"jsonrpc": "2.0", "id": rid, "method": "tools/list"})
    return [t["name"] for t in _recv(p)["result"]["tools"]]


def _add(p, rid):
    _send(p, {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
              "params": {"name": "add", "arguments": {"a": 20, "b": 22}}})
    return _recv(p)


def _close(p):
    p.stdin.close()
    p.wait(timeout=15)
    return p.stderr.read()


def _cli(*args):
    return subprocess.run([*WRAP, *args], capture_output=True, text=True, check=True).stdout


def test_rug_pull_inside_one_session_then_approve(tmp_path):
    db = str(tmp_path / "z.db")
    p = _open(db)
    try:
        assert _names(p, 2) == ["add"]
        first = _add(p, 3)
        assert not first["result"].get("isError") and "42" in json.dumps(first)
        assert _names(p, 4) == []  # description changed -> tool withdrawn
        blocked = _add(p, 5)
        assert blocked["result"]["isError"] is True and "quarantined" in json.dumps(blocked)
    finally:
        err = _close(p)
    assert "pins server=rug" in err

    listing = _cli("pins", "list", "--db", db)
    assert "add" in listing and "quarantined" in listing and "logs usage" not in listing

    _cli("pins", "approve", "rug", "add", "--db", db)
    p = _open(db, RUGPULL_V2="1")  # same text the server switched to
    try:
        assert _names(p, 2) == ["add"]
        assert "42" in json.dumps(_add(p, 3))
    finally:
        _close(p)


def test_change_between_sessions_is_caught(tmp_path):
    db = str(tmp_path / "z.db")
    p = _open(db)
    try:
        assert _names(p, 2) == ["add"]
    finally:
        _close(p)
    p = _open(db, RUGPULL_V2="1")
    try:
        assert _names(p, 2) == []
    finally:
        _close(p)


def test_poisoned_from_the_start_is_never_shown(tmp_path):
    db = str(tmp_path / "z.db")
    p = _open(db, RUGPULL_POISON="1")
    try:
        assert _names(p, 2) == []
        assert _add(p, 3)["result"]["isError"] is True
    finally:
        _close(p)
    out = subprocess.run(
        [*WRAP, "log", "--db", db, "-n", "20"], capture_output=True, text=True, check=True
    ).stdout
    assert "[pin]" in out and "IMPORTANT" not in out and "id_rsa" not in out
