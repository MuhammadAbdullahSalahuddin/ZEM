from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Annotated

import typer

from zem.audit.store import SqliteAudit
from zem.detectors.net_guard import NetGuard
from zem.detectors.path_guard import PathGuard
from zem.detectors.secret_guard import SecretGuard
from zem.detectors.shell_guard import ShellGuard
from zem.detectors.tool_guard import ToolGuard
from zem.pipeline.orchestrator import Pipeline, make_interceptor
from zem.policy.loader import PolicyError, load_policy
from zem.protocol.stdio_proxy import run_proxy

app = typer.Typer(no_args_is_help=True, add_completion=False)
DEFAULT_DB = os.environ.get("ZEM_DB", str(Path.home() / ".zem" / "zem.db"))


@app.command()
def wrap(
    cmd: Annotated[list[str], typer.Argument(help="Command that starts the real MCP server")],
    policy: Annotated[
        str, typer.Option("--policy", help="Policy name or YAML path")
    ] = "coding-agent",
    root: Annotated[
        list[str] | None, typer.Option("--root", help="Allowed folder. Repeatable.")
    ] = None,
    server_name: Annotated[str, typer.Option("--server-name", help="Label in logs")] = "default",
    db: Annotated[str, typer.Option("--db", help="SQLite audit file")] = DEFAULT_DB,
) -> None:
    """Run an MCP server behind ZEM:  zem wrap -- <command...>"""
    try:
        pol = load_policy(policy)
    except PolicyError as exc:  # fail closed: never run unprotected
        typer.echo(f"[zem] {exc}", err=True)
        raise typer.Exit(2) from exc
    roots = root or pol.allowed_roots
    pipeline = Pipeline(
        [
            PathGuard(roots),
            SecretGuard(),
            ShellGuard(),
            NetGuard(pol.net_allowlist),
            ToolGuard(pol.tools.allow, pol.tools.deny),
        ],
        hard_codes=pol.hard_deny_codes,
    )
    interceptor = make_interceptor(pipeline, server=server_name, audit=SqliteAudit(db))
    code = asyncio.run(run_proxy(cmd, interceptor))
    raise typer.Exit(code)


def _fmt(r: dict) -> str:
    import json

    reasons = "; ".join(json.loads(r["reasons"])) or "-"
    return (
        f"{r['seq']:>5} {r['ts'][11:19]} {r['decision']:<5} risk={r['risk']:.2f} "
        f"{r['tool']:<14} {reasons}"
    )


@app.command("log")
def log_cmd(
    db: Annotated[str, typer.Option("--db")] = DEFAULT_DB,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    decision: Annotated[str | None, typer.Option("--decision", help="allow|deny")] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f")] = False,
) -> None:
    """Show recent ZEM decisions."""
    store = SqliteAudit(db)
    last = 0
    for r in store.recent(limit, decision):
        typer.echo(_fmt(r))
        last = r["seq"]
    try:
        while follow:
            time.sleep(0.5)
            for r in store.after(last, decision):
                typer.echo(_fmt(r))
                last = r["seq"]
    except KeyboardInterrupt:
        pass


@app.command()
def version() -> None:
    """Print the ZEM version."""
    typer.echo("zem 0.1.0")


if __name__ == "__main__":
    app()
