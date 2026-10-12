from __future__ import annotations

import os
import posixpath
import re
from urllib.parse import unquote

from zem.contracts.models import Severity, Signal, ToolCallContext
from zem.detectors._util import iter_strings

# Argument names that normally hold a path. Always checked.
PATH_KEYS = {
    "path", "file", "filename", "filepath", "file_path", "dir",
    "directory", "folder", "cwd", "source", "destination", "src", "dst",
}
# Any key ending like this is treated as a path too (read_path, target_dir, ...)
PATH_SUFFIXES = (
    "path", "paths", "file", "files", "filename", "dir", "dirs",
    "directory", "folder", "cwd", "src", "dst", "source", "destination",
)

# (code, pattern): files an agent should never read, even inside the workspace.
# Matched against a lower-cased path, so write the patterns in lower case.
SENSITIVE = (
    ("env_file", re.compile(r"(^|/)\.env(\.(?!example$|sample$)[\w.-]+)?$")),
    ("ssh_key", re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$")),
    ("ssh_dir", re.compile(r"(^|/)\.ssh(/|$)")),
    ("system_auth", re.compile(r"^/etc/(passwd|shadow|gshadow|sudoers)")),
    ("aws_credentials", re.compile(r"(^|/)\.aws(/|$)")),
    ("token_file", re.compile(r"(^|/)\.(npmrc|pypirc|netrc|pgpass)$")),
    ("git_config", re.compile(r"(^|/)\.git/config$")),
    ("kube_config", re.compile(r"(^|/)\.kube/config$")),
    ("proc_environ", re.compile(r"^/proc/[^/]+/environ$")),
)


def _decode(raw: str) -> str:
    """Undo URL-encoding (up to 3 layers), unify slashes, unwrap file: URLs."""
    text = raw
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    text = text.replace("\\", "/")
    if text.lower().startswith("file:"):
        text = "/" + text[5:].lstrip("/")
    return text


def _is_pathlike(key: str, text: str) -> bool:
    k = key.lower()
    if k in PATH_KEYS or k.endswith(PATH_SUFFIXES):
        return True
    if "://" in text or any(ch.isspace() for ch in text):
        return False  # URLs and prose are not paths
    if text.startswith(("~", "..")):
        return True
    return text.startswith("/") and text.count("/") >= 2  # "/etc/passwd", not "/approve"


def _escapes(path: str, roots: list[str]) -> bool:
    """True if `path` points outside every allowed root (symlinks resolved)."""
    if path.startswith("~"):  # the tool may expand ~ to the home folder
        return True
    for root in roots:
        full = os.path.realpath(posixpath.join(root, path))
        if full == root or full.startswith(root.rstrip("/") + "/"):
            return False
    return True


class PathGuard:
    name = "path_guard"

    def __init__(self, allowed_roots: list[str]) -> None:
        self.roots = [os.path.realpath(r) for r in allowed_roots]

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        signals: list[Signal] = []
        for key, raw in iter_strings(ctx.arguments):
            decoded = _decode(raw)

            if "\x00" in decoded:
                signals.append(self._signal("null_byte", key, raw))
                continue

            has_dotdot = ".." in decoded.split("/")
            if not (_is_pathlike(key, decoded) or has_dotdot):
                continue  # prose or other data: leave it alone

            if _escapes(decoded, self.roots):
                was_encoded = decoded != raw.replace("\\", "/")
                code = "encoded_path_escape" if was_encoded else "path_escape"
                signals.append(self._signal(code, key, raw))

            hit = self._sensitive(decoded)
            if hit:
                signals.append(self._signal(f"sensitive_{hit}", key, raw))
        return signals

    def _sensitive(self, decoded: str) -> str | None:
        candidates = [posixpath.normpath(decoded)]
        candidates += [os.path.realpath(posixpath.join(r, decoded)) for r in self.roots]
        candidates = [c.lower() for c in candidates]  # ".ENV" is still ".env"
        for code, pattern in SENSITIVE:
            if any(pattern.search(c) for c in candidates):
                return code
        return None

    def _signal(self, code: str, key: str, raw: str) -> Signal:
        return Signal(
            detector=self.name,
            code=code,
            weight=0.9,
            severity=Severity.HIGH,
            evidence=f"{key}={raw[:100]!r} blocked ({code})",
            hard_deny=True,
        )
