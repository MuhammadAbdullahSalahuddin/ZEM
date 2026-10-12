from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote, urlparse

from zem.contracts.models import Severity, Signal, ToolCallContext
from zem.detectors._util import iter_strings

URL_RE = re.compile(r"\b(?:https?|ftp|wss?)://[^\s'\"<>)\]}]+", re.IGNORECASE)
META_RE = re.compile(r"169\.254\.169\.254|metadata\.google\.internal|fd00:ec2::254", re.IGNORECASE)
# decimal/hex/octal-looking hosts such as 2852039166 or 0xa9fea9fe
NUMERIC_HOST = re.compile(r"(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*", re.IGNORECASE)


class NetGuard:
    name = "net_guard"

    def __init__(self, allowlist: list[str] | None = None) -> None:
        self.allow = [d.lower().strip(".") for d in (allowlist or [])]

    def _allowed(self, host: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in self.allow)

    def _sig(self, code: str, weight: float, sev: Severity, text: str) -> Signal:
        shown = text if len(text) <= 80 else text[:80] + "..."
        return Signal(
            detector=self.name,
            code=code,
            weight=weight,
            severity=sev,
            evidence=shown,
            hard_deny=True,
        )

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        out: list[Signal] = []
        for _key, text in iter_strings(ctx.arguments):
            if META_RE.search(text):  # never allowlistable
                out.append(self._sig("cloud_metadata", 1.0, Severity.CRITICAL, text))
            for m in URL_RE.finditer(text):
                url = m.group(0)
                try:
                    host = unquote(urlparse(url).hostname or "").lower().rstrip(".")
                except ValueError:
                    out.append(self._sig("invalid_url", 0.9, Severity.HIGH, url))
                    continue
                if not host or host in self.allow:
                    continue
                try:
                    ipaddress.ip_address(host)
                    out.append(self._sig("raw_ip_host", 0.9, Severity.HIGH, url))
                    continue
                except ValueError:
                    pass
                if NUMERIC_HOST.fullmatch(host):
                    out.append(self._sig("obfuscated_ip_host", 0.9, Severity.HIGH, url))
                elif self.allow and not self._allowed(host):
                    out.append(self._sig("unknown_domain", 0.4, Severity.MEDIUM, url))
        return out
