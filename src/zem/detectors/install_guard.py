from __future__ import annotations

import re

from zem.contracts.models import Severity, Signal, ToolCallContext
from zem.detectors.shell_guard import (
    MAX_COMMAND_CHARS,
    SHELL_KEYS,
    SHELL_TOOL,
    _normalize,
    _texts,
)

POPULAR = frozenset(
    ["requests", "numpy", "pandas", "flask", "django", "fastapi", "pydantic", "pytest", "ruff", "mypy", "black", "httpx", "aiohttp", "sqlalchemy", "scipy", "matplotlib", "pillow", "pyyaml", "click", "typer", "rich", "boto3", "uvicorn", "setuptools", "wheel", "pip", "uv", "poetry", "cryptography", "jinja2", "beautifulsoup4", "lxml", "scikit-learn", "tensorflow", "torch", "openai", "anthropic", "tqdm", "python-dotenv", "express", "react", "vue", "lodash", "axios", "typescript", "webpack", "vite", "next", "eslint", "prettier", "jest", "tailwindcss", "chalk", "commander"]
)
SUSPICIOUS_TAILS = frozenset({"security", "patch", "update", "fix", "official", "secure", "helper"})
SPLIT = re.compile(r"\s*(?:&&|\|\||[;&|\n])\s*")
VALUE_FLAGS = frozenset(
    {"-r", "--requirement", "-e", "--editable", "-c", "--constraint", "-i", "--index-url",
     "--extra-index-url", "-t", "--target", "--prefix", "-f", "--find-links"}
)


def _osa(a: str, b: str) -> int:
    """Edit distance where swapping two neighbouring letters costs 1 ('reqeusts' -> 'requests')."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = int(a[i - 1] != b[j - 1])
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _targets(tokens: list[str]) -> tuple[str, list[str], bool] | None:
    """(ecosystem, argument tokens, first_only) if this command installs packages."""
    while tokens and (tokens[0] == "sudo" or ("=" in tokens[0] and not tokens[0].startswith("-"))):
        tokens = tokens[1:]
    if not tokens:
        return None
    head, rest = tokens[0].rsplit("/", 1)[-1], tokens[1:]
    if head in {"python", "python3"} and rest[:2] == ["-m", "pip"]:
        head, rest = "pip", rest[2:]
    if head in {"pip", "pip3"} and rest[:1] == ["install"]:
        return "pypi", rest[1:], False
    if head == "uv" and rest[:1] == ["add"]:
        return "pypi", rest[1:], False
    if head == "uv" and rest[:2] == ["pip", "install"]:
        return "pypi", rest[2:], False
    if head in {"npm", "pnpm", "yarn", "bun"} and rest[:1] and rest[0] in {"install", "i", "add"}:
        return "npm", rest[1:], False
    if head == "npx":
        return "npm", rest, True  # only the first non-flag word is a package
    return None


def _base(tok: str, eco: str) -> str:
    if eco == "npm":
        if tok.startswith("@"):
            name = "@" + tok[1:].partition("@")[0]
        else:
            name = tok.split("@", 1)[0]
    else:
        name = re.split(r"[=<>!~\[;]", tok, maxsplit=1)[0]
    return name.lower().replace("_", "-")


def _names(eco: str, args: list[str], first_only: bool) -> list[str]:
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in VALUE_FLAGS:
            skip = True
            continue
        if a.startswith(("-", ".", "/", "~", "git+")) or "://" in a:           
            continue
        
        name = _base(a, eco)
        if name:
            out.append(name)
            if first_only:
                break
    return out


def _lookalike(name: str) -> str | None:
    if name in POPULAR or len(name) > 64:
        return None
    for k in POPULAR:
        if len(name) >= 5 and abs(len(name) - len(k)) <= 1 and _osa(name, k) == 1:
            return k
        if name.startswith(k + "-") and any(
            t in SUSPICIOUS_TAILS for t in name[len(k) + 1 :].split("-")
        ):
            return k
    return None


class InstallGuard:
    name = "install_guard"

    def __init__(self, known: list[str] | None = None) -> None:
        self.known = POPULAR | {k.lower().replace("_", "-") for k in (known or [])}

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        scan_all = bool(SHELL_TOOL.search(ctx.tool.lower()))
        unknown: list[str] = []
        lookalikes: list[str] = []
        for key, raw in _texts(ctx.arguments):
            if not (scan_all or key in SHELL_KEYS) or len(raw) > MAX_COMMAND_CHARS:
                continue  # oversized is ShellGuard's hard deny
            for segment in SPLIT.split(_normalize(raw)):
                found = _targets(segment.split())
                if found is None:
                    continue
                eco, args, first_only = found
                for pkg in _names(eco, args, first_only):
                    if pkg in self.known:
                        continue
                    unknown.append(pkg)
                    twin = _lookalike(pkg)
                    if twin:
                        lookalikes.append(f"{pkg}~{twin}")
        out: list[Signal] = []
        if unknown:
            out.append(Signal(
                detector=self.name, code="unpinned_install", weight=0.35,
                severity=Severity.MEDIUM, evidence="unfamiliar: " + ", ".join(unknown[:3]),
            ))
        if lookalikes:
            out.append(Signal(
                detector=self.name, code="typosquat_suspect", weight=0.30,
                severity=Severity.MEDIUM, evidence="looks like: " + ", ".join(lookalikes[:3]),
            ))
        return out
