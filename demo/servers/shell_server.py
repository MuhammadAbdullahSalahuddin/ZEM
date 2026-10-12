"""Fake vulnerable shell server for ZEM demos.

SIMULATED: it NEVER executes anything. It returns canned text so demos are safe.
DELIBERATELY NAIVE: it "accepts" any command, which is the hole ZEM closes.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("shell")

CANNED = {
    "git status": "On branch main\nnothing to commit, working tree clean",
    "ls -la": "total 8\n-rw-r--r-- 1 demo demo 40 README.md\ndrwxr-xr-x 2 demo demo 60 src",
    "pytest -q": "3 passed in 0.10s",
}


@mcp.tool()
def shell_run(command: str) -> str:
    """Run a shell command. SIMULATED: nothing is ever executed."""
    if command in CANNED:
        return CANNED[command]
    return f"[SIMULATION ONLY - NOT EXECUTED] the agent's command went through: {command}"


if __name__ == "__main__":
    mcp.run()  # stdio transport

