from __future__ import annotations

import posixpath
from urllib.parse import unquote

from zem.contracts.models import Severity, Signal, ToolCallContext
from zem.detectors._util import iter_strings

# Argument names that normally hold a path. These are always checked.
PATH_KEYS = {
    "path",
    "file",
    "filename",
    "filepath",
    "dir",
    "directory",
    "folder",
    "cwd",
    "source",
    "destination",
    "src",
    "dst",
}


def _decode(raw: str) -> str:
    """Undo URL-encoding (up to 3 layers) and unify slashes."""
    text = raw
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    return text.replace("\\", "/")


def _escapes(path: str, roots: list[str]) -> bool:
    """True if `path` points outside every allowed root."""
    if path.startswith("~"):  # the tool may expand ~ to the home folder
        return True
    for root in roots:
        # join() keeps an absolute `path` as-is, so "/etc/x" ignores the root.
        full = posixpath.normpath(posixpath.join(root, path))
        if full == root or full.startswith(root.rstrip("/") + "/"):
            return False
    return True


class PathGuard:
    name = "path_guard"

    def __init__(self, allowed_roots: list[str]) -> None:
        self.roots = [posixpath.normpath(r) for r in allowed_roots]

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        signals: list[Signal] = []
        for key, raw in iter_strings(ctx.arguments):
            decoded = _decode(raw)

            if "\x00" in decoded:
                signals.append(self._signal("null_byte", key, raw))
                continue

            is_path_key = key.lower() in PATH_KEYS
            has_dotdot = ".." in decoded.split("/")
            if not (is_path_key or has_dotdot):
                continue  # prose or other data: not a path, leave it alone

            if _escapes(decoded, self.roots):
                was_encoded = decoded != raw.replace("\\", "/")
                code = "encoded_path_escape" if was_encoded else "path_escape"
                signals.append(self._signal(code, key, raw))
        return signals

    def _signal(self, code: str, key: str, raw: str) -> Signal:
        return Signal(
            detector=self.name,
            code=code,
            weight=0.9,
            severity=Severity.HIGH,
            evidence=f"{key}={raw[:100]!r} resolves outside allowed roots",
            hard_deny=True,
        )
