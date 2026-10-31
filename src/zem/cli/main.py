from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from zem.audit.pin_store import PinStore
from zem.audit.store import SqliteAudit
from zem.detectors.install_guard import InstallGuard
from zem.detectors.net_guard import NetGuard
from zem.detectors.outbound_guard import OutboundGuard
from zem.detectors.path_guard import PathGuard
from zem.detectors.pin_guard import PinGuard, PinState, safe_name
from zem.detectors.secret_guard import SecretGuard
from zem.detectors.shell_guard import ShellGuard
from zem.detectors.tool_guard import ToolGuard
from zem.detectors.unicode_guard import UnicodeGuard
from zem.pipeline.egress import make_egress_hook
from zem.pipeline.hooks import chain_hooks
from zem.pipeline.orchestrator import Pipeline, make_interceptor
from zem.pipeline.pins import make_pin_hook
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
    reasoner_name: Annotated[
        str | None, typer.Option("--reasoner", envvar="ZEM_REASONER", help="mock|nebius")
    ] = None,
) -> None:
    """Run an MCP server behind ZEM:  zem wrap -- <command...>"""
    try:
        pol = load_policy(policy)
    except PolicyError as exc:  # fail closed: never run unprotected
        typer.echo(f"[zem] {exc}", err=True)
        raise typer.Exit(2) from exc
    roots = root or pol.allowed_roots
    pin_store = PinStore(db) if pol.pins.enabled else None
    pin_state = PinState(pin_store.quarantined(server_name) if pin_store else None)
    pipeline = Pipeline(
        [
            PathGuard(roots),
            SecretGuard(),
            ShellGuard(),
            NetGuard(pol.net_allowlist),
            UnicodeGuard(),
            ToolGuard(pol.tools.allow, pol.tools.deny),
            InstallGuard(pol.known_packages),
            OutboundGuard(),
            PinGuard(pin_state),
        ],
        hard_codes=pol.hard_deny_codes,
    )
    reasoner = None
    which = (reasoner_name or "").lower()
    if which == "mock":
        from zem.reasoning.mock_reasoner import MockReasoner

        reasoner = MockReasoner()
    elif which == "nebius":
        try:  # file name comes from the master plan layout; confirm the constructor with Karachi
            from zem.reasoning.nebius_reasoner import NebiusReasoner

            reasoner = NebiusReasoner()
        except Exception as exc:  # fail closed: never silently run without the judge you asked for
            typer.echo(f"[zem] cannot start nebius reasoner: {exc}", err=True)
            raise typer.Exit(2) from exc
    elif which not in ("", "none"):
        typer.echo(f"[zem] unknown reasoner {which!r} (use mock|nebius)", err=True)
        raise typer.Exit(2)
    if pol.judge.enabled and reasoner is None:
        typer.echo("[zem] WARNING: judge enabled but no reasoner; gray calls use on_error", err=True)
    sid = uuid4().hex  # one id shared by request rows and result rows
    audit = SqliteAudit(db)
    interceptor = make_interceptor(
        pipeline, server=server_name, session_id=sid, audit=audit, reasoner=reasoner, policy=pol
    )
    hooks = []
    if pin_store is not None:
        hooks.append(
            make_pin_hook(
                pol.pins, store=pin_store, state=pin_state, audit=audit,
                server=server_name, session_id=sid,
            )
        )
    if pol.egress.enabled:
        hooks.append(make_egress_hook(pol.egress, audit=audit, server=server_name, session_id=sid))
    hook = chain_hooks(*hooks) if hooks else None
    code = asyncio.run(run_proxy(cmd, interceptor, hook))    

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
def stats(db: Annotated[str, typer.Option("--db")] = DEFAULT_DB) -> None:
    """% of calls decided without a model, and judge latency p50/p95."""
    rows = SqliteAudit(db).db.execute("SELECT event_json FROM events").fetchall()
    events = [json.loads(r["event_json"]) for r in rows]
    events = [e for e in events if not e["context"]["tool"].endswith(("[result]", "[pin]"))]
    if not events:
        typer.echo("no events")
        return
    judged = sorted(
        e["latency_breakdown_ms"].get("judge", 0) for e in events if e.get("judge")
    )
    pct = 100 * (len(events) - len(judged)) / len(events)
    typer.echo(f"calls={len(events)} without_model={pct:.1f}% judged={len(judged)}")
    if judged:
        p = lambda q: judged[min(len(judged) - 1, int(q * len(judged)))]
        typer.echo(f"judge latency ms: p50={p(0.5)} p95={p(0.95)}")


@app.command()
def version() -> None:
    """Print the ZEM version."""
    typer.echo("zem 0.1.0")

pins_app = typer.Typer(no_args_is_help=True, help="Review and approve pinned tool definitions")
app.add_typer(pins_app, name="pins")


@pins_app.command("list")
def pins_list(
    server: Annotated[str | None, typer.Option("--server")] = None,
    db: Annotated[str, typer.Option("--db")] = DEFAULT_DB,
) -> None:
    """Show every pinned tool and whether it is quarantined."""
    rows = PinStore(db).rows(server)
    if not rows:
        typer.echo("no pins")
        return
    for p in rows:
        pend = f" pending={p.pending_hash[:12]}" if p.pending_hash else ""
        typer.echo(
            f"{safe_name(p.server):<12} {safe_name(p.tool):<24} {p.status:<11} "
            f"{p.hash[:12]}{pend} {safe_name(p.reason, 40)} {p.first_seen[:10]}"
        )


@pins_app.command("approve")
def pins_approve(
    server: Annotated[str, typer.Argument()],
    tool: Annotated[str, typer.Argument()],
    db: Annotated[str, typer.Option("--db")] = DEFAULT_DB,
) -> None:
    """Accept the tool's current definition. Restart the wrapped server afterwards."""
    if PinStore(db).approve(server, tool):
        typer.echo(f"approved {safe_name(server)}/{safe_name(tool)}. Restart the wrapped server.")
        return
    typer.echo("no such pin", err=True)
    raise typer.Exit(1)


@pins_app.command("forget")
def pins_forget(
    server: Annotated[str, typer.Argument()],
    tool: Annotated[str | None, typer.Argument()] = None,
    db: Annotated[str, typer.Option("--db")] = DEFAULT_DB,
) -> None:
    """Delete pins (one tool, or the whole server). Use after a deliberate server upgrade."""
    n = PinStore(db).forget(server, tool)
    typer.echo(f"forgot {n} pin(s)")
@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    db: Annotated[str, typer.Option("--db")] = DEFAULT_DB,
) -> None:
    """Start the dashboard API:  zem serve"""
    import uvicorn

    os.environ["ZEM_DB"] = db  # the API reads this when it loads
    uvicorn.run("zem.api.app:app", host=host, port=port)

if __name__ == "__main__":
    app()
