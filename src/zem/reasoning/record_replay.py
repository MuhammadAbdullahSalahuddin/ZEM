"""Record/replay wrapper for any Reasoner (R2-K4).

  record : call the real judge, save the verdict to a cassette file.
  replay : never call the network; answer from the cassette. A miss is an error,
           so CI can never silently spend tokens or become flaky.
  auto   : replay on a hit, record on a miss (handy for local development).

Cassette keys are a hash of what the judge actually decides on (tool, arguments,
signals, objective, recent calls, intel, depth, prompt version) and NOT the
volatile call_id / session_id / timestamp. Failed/fallback verdicts are never
recorded, so a temporary outage can't get frozen into the tests.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from zem.contracts.models import IntelResult, JudgeVerdict, Reasoner, ToolCallContext
from zem.reasoning.prompts import PROMPT_VERSION

Mode = Literal["replay", "record", "auto"]
CASSETTE_VERSION = 1


class CassetteError(RuntimeError):
    """Cassette is unreadable or has no recording for this call."""


def request_key(
    ctx: ToolCallContext,
    depth: str,
    intel: IntelResult | None,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    payload: dict[str, Any] = {
        "prompt_version": prompt_version,
        "depth": depth,
        "server": ctx.server,
        "tool": ctx.tool,
        "arguments": ctx.arguments,
        "signals": [s.model_dump(mode="json") for s in ctx.signals],
        "objective": ctx.objective,
        "recent_calls": ctx.recent_calls,
        "intel": intel.model_dump(mode="json") if intel else None,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RecordReplayReasoner:
    def __init__(
        self,
        inner: Reasoner | None,
        cassette_path: Path | str,
        mode: Mode = "replay",
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        if mode in ("record", "auto") and inner is None:
            raise ValueError(f"mode '{mode}' needs a real reasoner to record from")
        self.inner = inner
        self.path = Path(cassette_path)
        self.mode: Mode = mode
        self.prompt_version = prompt_version

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            entries = data["entries"]
            if data.get("version") != CASSETTE_VERSION or not isinstance(entries, dict):
                raise ValueError("bad cassette shape")
            return dict(entries)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CassetteError(f"cassette {self.path} is unreadable: {type(exc).__name__}") from exc

    def _save(self, entries: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        doc = {"version": CASSETTE_VERSION, "entries": entries}
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: no half-written cassette

    async def judge(
        self,
        ctx: ToolCallContext,
        *,
        depth: Literal["fast", "deep"],
        intel: IntelResult | None = None,
    ) -> JudgeVerdict:
        key = request_key(ctx, depth, intel, self.prompt_version)

        if self.mode in ("replay", "auto"):
            entry = self._load().get(key)
            if entry is not None:
                return JudgeVerdict.model_validate(entry)
            if self.mode == "replay":
                raise CassetteError(
                    f"no recording for {ctx.server}.{ctx.tool} (key {key[:12]}). "
                    "Re-record with mode='record'."
                )

        assert self.inner is not None  # guaranteed by __init__ for record/auto
        verdict = await self.inner.judge(ctx, depth=depth, intel=intel)
        if "judge_error" not in verdict.risk_tags:
            entries = self._load()
            entries[key] = verdict.model_dump(mode="json")
            self._save(entries)
        return verdict

