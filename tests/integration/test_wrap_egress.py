import json
import subprocess
import sys

LAUNCH = [
    sys.executable, "-c", "from zem.cli.main import app; app()", "wrap",
    "--root", "/workspace", "--server-name", "fs",
    "--", sys.executable, "demo/servers/fs_server.py",
]
AWS = "AKIA" + "IOSFODNN7EXAMPLE"


def _send(p, obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def _recv(p):
    line = p.stdout.readline()
    assert line, "proxy closed stdout unexpectedly"
    return json.loads(line)


def _read(p, rid, path):
    _send(p, {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
              "params": {"name": "read_file", "arguments": {"path": path}}})
    return _recv(p)


def test_results_are_scrubbed_on_the_way_back():
    p = subprocess.Popen(
        LAUNCH, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        _send(p, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"}}})
        assert _recv(p)["id"] == 1
        _send(p, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        key = _read(p, 2, "config/settings.py")
        assert AWS not in json.dumps(key)  # in content AND structuredContent
        assert "[REDACTED:aws_access_key]" in json.dumps(key)

        csv = _read(p, 3, "data/customers.csv")
        blob = json.dumps(csv)
        assert "35202-1234567-1" not in blob and "[REDACTED:cnic]" in blob
        assert "ali@example.com" in blob  # contact is flag-only by default

        readme = _read(p, 4, "README.md")
        assert "ignore prior instructions" in json.dumps(readme)  # flagged, not edited
    finally:
        p.stdin.close()
        p.wait(timeout=15)
    err = p.stderr.read()
    assert "egress tool=read_file" in err and AWS not in err
    out = subprocess.run(
        [sys.executable, "-c", "from zem.cli.main import app; app()", "log"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "read_file[result]" in out and "redact" in out and AWS not in out
