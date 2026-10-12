"""Run the R1 scenarios against the fake servers, with or without ZEM.

    python demo/run_scenarios.py              # protected: attacks denied, benign allowed
    python demo/run_scenarios.py --no-zem     # unprotected: shows what the attacks do
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SERVERS = {"fs": HERE / "servers" / "fs_server.py", "shell": HERE / "servers" / "shell_server.py"}
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
BLOCK_MARK = "Blocked by ZEM policy"
WHY = {  # plain-English reasons for the --story view
    "path_escape": "it tried to step outside its allowed folder",
    "encoded_path_escape": "it tried to step outside its allowed folder (disguised)",
    "pipe_to_interpreter": "it tried to download and run unknown code",
    "aws_access_key": "it was about to leak a secret key",
    "unknown_domain": "it tried to reach an unapproved website",
    "raw_ip_host": "it tried to reach a hidden internet address",
    "cloud_metadata": "it tried to read the cloud machine's secrets",
    "sensitive_": "it tried to read a protected secrets file",
    "hidden_unicode": "it hid invisible text inside its request",
    "oversized_command": "its command was suspiciously huge",
       }


def _fill(value: Any) -> Any:
    if isinstance(value, str):
        value = re.sub(r"\{\{PAD:(\d+)\}\}", lambda m: "A" * int(m.group(1)), value)
        return value.replace("{{AWS_KEY}}", AWS_KEY)
    if isinstance(value, dict):
        return {k: _fill(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v) for v in value]
    return value


def _launch(server: str, *, zem: bool, policy: str, db: str) -> subprocess.Popen[str]:
    cmd = [sys.executable, str(SERVERS[server])]
    if zem:
        cmd = [
            sys.executable, "-c", "from zem.cli.main import app; app()", "wrap",
            "--policy", policy, "--root", "/workspace", "--server-name", server,
            "--db", db, "--", *cmd,
        ]
    return subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )


def _send(p: subprocess.Popen[str], obj: dict[str, Any]) -> None:
    assert p.stdin is not None
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def _recv(p: subprocess.Popen[str]) -> dict[str, Any]:
    assert p.stdout is not None
    line = p.stdout.readline()
    if not line:
        raise RuntimeError("server closed stdout unexpectedly")
    return json.loads(line)  # type: ignore[no-any-return]


def _run_server(
    server: str, items: list[dict[str, Any]], **kw: Any
) -> list[tuple[dict[str, Any], str, str]]:
    p = _launch(server, **kw)
    results = []
    try:
        _send(p, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "scenarios", "version": "0"}}})
        _recv(p)
        _send(p, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        for i, sc in enumerate(items, start=1):
            _send(p, {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                      "params": {"name": sc["tool"], "arguments": _fill(sc["args"])}})
            result = _recv(p).get("result", {})
            text = " ".join(c.get("text", "") for c in result.get("content", []))
            blocked = bool(result.get("isError")) and BLOCK_MARK in text
            results.append((sc, "deny" if blocked else "allow", text))
    finally:
        assert p.stdin is not None
        p.stdin.close()
        p.wait(timeout=15)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-zem", action="store_true", help="talk to the fake servers directly")
    ap.add_argument("--policy", default="coding-agent")
    ap.add_argument("--db", default=os.environ.get("ZEM_DB"))
    ap.add_argument("--story", action="store_true", help="plain-English output for demos")
    ap.add_argument("--file", default=str(HERE / "scenarios" / "scenarios.yaml"),
                    help="scenario file to run")
    args = ap.parse_args(argv)

    if hasattr(signal, "SIGALRM"):  # never hang forever
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("timed out")))
        signal.alarm(60)

    zem = not args.no_zem
    db = args.db or str(Path(tempfile.mkdtemp(prefix="zem-")) / "zem.db")
    scenarios = yaml.safe_load(Path(args.file).read_text())

    print("=== WITH ZEM ===" if zem else "=== WITHOUT ZEM (unprotected) ===")
    failures = 0
    by_id: dict[str, tuple[dict[str, Any], str, str]] = {}
    for server in SERVERS:
        items = [s for s in scenarios if s["server"] == server]
        for row in _run_server(server, items, zem=zem, policy=args.policy, db=db):
            by_id[row[0]["id"]] = row
    for sc in scenarios:  # print in file order, not server order
        _, got, text = by_id[sc["id"]]
        text = " ".join(text.split())  # one line per scenario
        short = (text[:95] + "...") if len(text) > 95 else text
        if args.story:
            why = next((w for c, w in WHY.items() if c in text), "ZEM's rules said no")
            what = sc.get("story", sc["id"])
            if zem:
                missed = sc["kind"] == "attack" and got == "allow"
                tag = "[BLOCKED]" if got == "deny" else "[ALLOWED]"
                note = f"\n           Why: {why}" if got == "deny" else ""
                if missed and sc.get("known_gap"):
                    note = "\n           Known limitation (listed in the README)"

                print(f"{tag}  {what}{note}")
            else:
                bad = sc["kind"] == "attack" and got == "allow"
                print(f"{'[DANGER: IT WORKED]' if bad else '[ok]':<21} {what}")
            
            wrong = zem and got != sc["expect"] and not sc.get("known_gap")
            failures += 1 if wrong else 0
            continue
        if zem:
            ok = got == sc["expect"] and (got == "allow" or sc.get("expect_reason", "") in text)
            gap = (not ok) and bool(sc.get("known_gap"))  # a miss we already know about
            failures += 0 if (ok or gap) else 1
            tag = "PASS" if ok else ("GAP " if gap else "FAIL")
            print(f"{tag}  {sc['id']:<18} {got:<5} {short}")
        else:
            went = sc["kind"] == "attack" and got == "allow"
            print(f"{'ATTACK SUCCEEDED' if went else 'ok':<17}  {sc['id']:<18} {short}")
    if zem:
        print(f"\n{'ALL SCENARIOS PASSED' if not failures else str(failures) + ' FAILED'}")
        print(f"decisions logged to {db}   ->   zem log --db {db}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
