from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo")


@mcp.tool()
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


@mcp.tool()
def read_file(path: str) -> str:
    """Read a file. DELIBERATELY NAIVE: no path restrictions (ZEM's R1 demo target)."""
    return Path(path).read_text()


if __name__ == "__main__":
    mcp.run()  # stdio transport
