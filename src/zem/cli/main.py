from __future__ import annotations

import asyncio
import os
from typing import Annotated

import typer

from zem.detectors.path_guard import PathGuard
from zem.detectors.secret_guard import SecretGuard
from zem.pipeline.orchestrator import Pipeline, make_interceptor
from zem.protocol.stdio_proxy import run_proxy

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def wrap(
    cmd: Annotated[
        list[str],
        typer.Argument(help="Command that starts the real MCP server"),
    ],
    policy: Annotated[
        str,
        typer.Option("--policy", help="Policy name (used from Friday's policy loader)"),
    ] = "coding-agent",
    root: Annotated[
        list[str] | None,
        typer.Option("--root", help="Allowed folder. Repeatable. Default: current folder."),
    ] = None,
    server_name: Annotated[
        str,
        typer.Option("--server-name", help="Label for this server in logs"),
    ] = "default",
) -> None:
    """Run an MCP server behind ZEM:  zem wrap -- <command...>"""
    roots = root or [os.getcwd()]
    pipeline = Pipeline([PathGuard(roots), SecretGuard()])
    interceptor = make_interceptor(pipeline, server=server_name)
    code = asyncio.run(run_proxy(cmd, interceptor))
    raise typer.Exit(code)


@app.command()
def version() -> None:
    """Print the ZEM version."""
    typer.echo("zem 0.0.0")


if __name__ == "__main__":
    app()
