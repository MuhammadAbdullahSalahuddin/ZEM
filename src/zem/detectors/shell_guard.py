from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from zem.contracts.models import Severity, Signal, ToolCallContext

SHELL_KEYS = {"cmd", "command", "script", "shell", "bash", "code", "args", "argv"}
SHELL_TOOL = re.compile(r"shell|exec|bash|terminal|command|run|\bsh\b")

# (code, regex, weight, severity, hard_deny)
RULES: tuple[tuple[str, str, float, Severity, bool], ...] = (
    (
        "pipe_to_interpreter",
        r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b",
        1.0,
        Severity.CRITICAL,
        True,
    ),
    (
        "decode_to_shell",
        r"\b(base64|xxd|openssl enc)\b[^|]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b",
        1.0,
        Severity.CRITICAL,
        True,
    ),
    (
        "rm_root_or_home",
        r"\brm\s+(-[a-zA-Z-]+\s+)+(/|~|\*|\$HOME)(/?\*?)(\s|$)",
        1.0,
        Severity.CRITICAL,
        True,
    ),
    (
        "reverse_shell",
        r"/dev/(tcp|udp)/|\bnc(at)?\b.*\s-\w*e\b|\bbash\s+-i\b|\bsocat\b.*exec",
        1.0,
        Severity.CRITICAL,
        True,
    ),
    ("fork_bomb", r":\(\)\s*\{", 1.0, Severity.CRITICAL, True),
    (
        "disk_destroy",
        r"\bmkfs(\.\w+)?\b|\bdd\b.*\bof=/dev/|\bshred\b",
        1.0,
        Severity.CRITICAL,
        True,
    ),
    (
        "secret_read",
        r"\b(cat|less|more|head|tail|cp|scp|base64)\b.*(\.env\b|id_rsa|id_ed25519|/etc/shadow|/etc/passwd|\.aws/credentials)",
        1.0,
        Severity.CRITICAL,
        True,
    ),
    # soft signals: logged only; policy can promote them via hard_deny_codes
    (
        "data_upload",
        r"\bcurl\b.*\s(-d|--data\S*|-F|--form|-T|--upload-file)\b",
        0.85,
        Severity.HIGH,
        False,
    ),
    (
        "privilege_change",
        r"\bsudo\b|\bchmod\s+(-\w+\s+)*0?777\b|\bchown\s+root",
        0.5,
        Severity.MEDIUM,
        False,
    ),
    ("shell_chaining", r"[;&`]|\$\(|\|", 0.15, Severity.LOW, False),
)
COMPILED = tuple((c, re.compile(p), w, s, h) for c, p, w, s, h in RULES)


def _texts(value: Any, key: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _texts(v, str(k).lower())
    elif isinstance(value, list | tuple):
        if value and all(isinstance(v, str) for v in value):
            yield key, " ".join(value)  # argv style: ["rm", "-rf", "/"]
        else:
            for v in value:
                yield from _texts(v, key)


def _normalize(s: str) -> str:
    s = re.sub(r"[\\'\"]", "", s)  # c'u'rl and cu\rl become curl
    return re.sub(r"\s+", " ", s).strip()


class ShellGuard:
    name = "shell_guard"

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        scan_all = bool(SHELL_TOOL.search(ctx.tool.lower()))
        signals: list[Signal] = []
        for key, raw in _texts(ctx.arguments):
            if not (scan_all or key in SHELL_KEYS):
                continue
            text = _normalize(raw)
            for code, rx, weight, sev, hard in COMPILED:
                if rx.search(text):
                    shown = raw if len(raw) <= 80 else raw[:80] + "..."
                    signals.append(
                        Signal(
                            detector=self.name,
                            code=code,
                            weight=weight,
                            severity=sev,
                            evidence=f"{key}: {shown}",
                            hard_deny=hard,
                        )
                    )
        return signals
