from __future__ import annotations

import re

from zem.contracts.models import Severity, Signal, ToolCallContext
from zem.detectors._util import iter_strings

# No honest tool call needs these: Unicode "tag" characters (invisible ASCII copy),
# bidi override/isolate controls ("Trojan Source"), variation-selector data hiding.
_HARD = re.compile("[\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069\U000e0100-\U000e01ef]")
# Zero-width characters: sometimes harmless (emoji joiners), often used to split keywords.
_SOFT = re.compile("[\u200b-\u200d\u2060\ufeff\u00ad\ufe00-\ufe0f]")


class UnicodeGuard:
    name = "unicode_guard"

    def inspect(self, ctx: ToolCallContext) -> list[Signal]:
        signals: list[Signal] = []
        for key, raw in iter_strings(ctx.arguments, clean_text=False):  # raw: we want the hidden bits
            if raw.isascii():
                continue
            if _HARD.search(raw):
                signals.append(self._sig("hidden_unicode", 0.95, True, key))
            elif _SOFT.search(raw):
                signals.append(self._sig("zero_width_chars", 0.5, False, key))
        return signals

    def _sig(self, code: str, weight: float, hard: bool, key: str) -> Signal:
        return Signal(
            detector=self.name, code=code, weight=weight,
            severity=Severity.HIGH if hard else Severity.MEDIUM,
            evidence=f"{key}: contains invisible characters", hard_deny=hard,
        )
