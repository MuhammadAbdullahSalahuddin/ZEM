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
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"


def _send(p, obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def _recv(p):
    line = p.stdout.readline()
    assert line, "proxy closed stdout unexpectedly"
    return json.loads(line)


def _call(p, call_id, tool, args):
    _send(
        p,
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        },
    )
    return _recv(p)


def test_attack_blocked_benign_allowed():
    p = subprocess.Popen(
        LAUNCH, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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

        blocked = _call(p, 2, "read_file", {"path": "../../etc/passwd"})
        assert blocked["result"]["isError"] is True
        assert "Blocked by ZEM" in json.dumps(blocked)

        leak = _call(p, 3, "echo", {"text": f"key is {AWS}"})
        assert leak["result"]["isError"] is True
        assert AWS not in json.dumps(leak)  # the key never echoes back

        ok = _call(p, 4, "echo", {"text": "hello zem"})
        assert not ok["result"].get("isError")
        assert "hello zem" in json.dumps(ok)
    finally:
        p.stdin.close()
        p.wait(timeout=15)
    err = p.stderr.read()
    assert "deny tool=read_file" in err and "allow tool=echo" in err
