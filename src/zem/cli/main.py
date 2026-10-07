from __future__ import annotations

import asyncio
from typing import Annotated

import typer

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
        typer.Option("--policy", help="Policy name (used from R1)"),
    ] = "coding-agent",
) -> None:
    """Run an MCP server behind ZEM:  zem wrap -- <command...>"""
    code = asyncio.run(run_proxy(cmd))
    raise typer.Exit(code)


@app.command()
def version() -> None:
    """Print the ZEM version."""
    typer.echo("zem 0.0.0")


if __name__ == "__main__":
    app()
