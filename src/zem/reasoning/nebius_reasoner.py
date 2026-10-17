"""NebiusReasoner: the real AI judge (R2-K1).

Calls Nemotron on Nebius Token Factory through its OpenAI-compatible API and
returns a JudgeVerdict. Design rules:
  - Strict JSON parsing. Anything that is not a valid verdict counts as a failure.
  - One retry, then fall back. We never crash the pipeline and never guess "allow".
  - On failure we return verdict "escalate" with tag "judge_error" and confidence 0,
    so the pipeline's deterministic result / on_error policy decides. A judge outage
    can therefore never turn into an allow.
  - Logs go to stderr via logging and never contain prompts, args, or the API key.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal

import openai
from pydantic import BaseModel, Field, ValidationError, field_validator

from zem.contracts.models import IntelResult, JudgeVerdict, ToolCallContext
from zem.reasoning.config import (
    ConfigError,
    ModelsConfig,
    NebiusSettings,
    load_models_config,
)
from zem.reasoning.prompts import PROMPT_VERSION, build_messages, prompt_hash

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # first try + one retry
MAX_REASON_CHARS = 400
MAX_TAGS = 8
MAX_TAG_CHARS = 40
_AUTH_STATUS = {401, 403}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class _RawVerdict(BaseModel):
    """What we accept from the model. Anything else is rejected."""

    verdict: Literal["allow", "deny", "escalate"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    risk_tags: list[str] = []
    needs_intel: bool = False
    intel_query: str | None = None

    @field_validator("reason")
    @classmethod
    def _cap_reason(cls, v: str) -> str:
        return v.strip()[:MAX_REASON_CHARS]

    @field_validator("risk_tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        return [str(t).strip().lower()[:MAX_TAG_CHARS] for t in v[:MAX_TAGS] if str(t).strip()]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull one JSON object out of model text (handles <think> and code fences)."""
    cleaned = _FENCE_RE.sub("", _THINK_RE.sub("", text).strip()).strip()
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        candidates.append(cleaned[start : end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def parse_verdict(text: str) -> _RawVerdict | None:
    data = _extract_json(text)
    if data is None:
        return None
    try:
        return _RawVerdict.model_validate(data)
    except ValidationError:
        return None


class NebiusReasoner:
    """Implements the Reasoner protocol from zem.contracts.models."""

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        config: ModelsConfig | None = None,
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or load_models_config()
        if client is not None:
            self._client = client  # injected (tests, record/replay)
            return
        key = api_key
        if key is None:
            secret = NebiusSettings().nebius_api_key
            key = secret.get_secret_value().strip() if secret else None
        if not key:
            raise ConfigError("NEBIUS_API_KEY is not set (env var or local .env file)")
        # max_retries=0: we own retry so the failure policy stays in one place.
        self._client = openai.AsyncOpenAI(
            api_key=key, base_url=self.config.base_url, max_retries=0
        )

    async def judge(
        self,
        ctx: ToolCallContext,
        *,
        depth: Literal["fast", "deep"],
        intel: IntelResult | None = None,
    ) -> JudgeVerdict:
        role = self.config.role("fast_judge" if depth == "fast" else "deep_judge")
        messages = build_messages(ctx, intel)
        phash = prompt_hash(messages, role.model)
        start = time.monotonic()
        tokens_in = tokens_out = 0
        last_error = "unknown"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await self._client.chat.completions.create(
                    model=role.model,
                    messages=messages,
                    max_tokens=role.max_tokens,
                    temperature=role.temperature,
                    timeout=role.timeout_s,
                    extra_body={"chat_template_kwargs": {"enable_thinking": role.enable_thinking}},
                )
            except (openai.OpenAIError, TimeoutError, OSError) as exc:
                last_error = type(exc).__name__
                logger.warning(
                    "judge call failed call_id=%s attempt=%d prompt=%s error=%s",
                    ctx.call_id, attempt, phash, last_error,
                )
                status = getattr(exc, "status_code", None)
                if status in _AUTH_STATUS:
                    break  # a retry cannot fix a bad key
                continue

            usage = getattr(resp, "usage", None)
            tokens_in += int(getattr(usage, "prompt_tokens", 0) or 0)
            tokens_out += int(getattr(usage, "completion_tokens", 0) or 0)

            choices = getattr(resp, "choices", None) or []
            content = (choices[0].message.content if choices else None) or ""
            parsed = parse_verdict(content)
            if parsed is not None:
                return JudgeVerdict(
                    verdict=parsed.verdict,
                    confidence=parsed.confidence,
                    reason=parsed.reason,
                    risk_tags=parsed.risk_tags,
                    needs_intel=parsed.needs_intel,
                    intel_query=parsed.intel_query,
                    model_id=role.model,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            last_error = "invalid_output"
            logger.warning(
                "judge returned invalid output call_id=%s attempt=%d prompt=%s",
                ctx.call_id, attempt, phash,
            )

        return JudgeVerdict(
            verdict="escalate",
            confidence=0.0,
            reason=f"judge_unavailable: {last_error}",
            risk_tags=["judge_error"],
            model_id=role.model,
            latency_ms=int((time.monotonic() - start) * 1000),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
