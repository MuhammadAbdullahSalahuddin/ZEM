import json
import subprocess
import sys

LAUNCH = [
    sys.executable,
    "-c",
    "from zem.cli.main import app; app()",
    "wrap",
    "--",
    sys.executable,
    "demo/servers/echo_server.py",
]


def _send(p: subprocess.Popen, obj: dict) -> None:
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def _recv(p: subprocess.Popen) -> dict:
    line = p.stdout.readline()
    assert line, "proxy closed stdout unexpectedly"
    return json.loads(line)  # fails loudly if anything non-JSON hit stdout


def test_echo_through_proxy():
    p = subprocess.Popen(
        LAUNCH,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _send(
            p,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
        )
        assert _recv(p)["id"] == 1
        _send(p, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(
            p,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "hello zem"}},
            },
        )
        reply = _recv(p)
        assert reply["id"] == 2
        assert "hello zem" in json.dumps(reply["result"])
    finally:
        p.stdin.close()
        p.wait(timeout=15)
    err = p.stderr.read()
    assert " allow tool=echo" in err
