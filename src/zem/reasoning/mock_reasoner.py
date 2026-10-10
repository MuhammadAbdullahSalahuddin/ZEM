"""Mock reasoner — a fake AI judge for tests and local dev.

Returns deterministic verdicts based on simple keyword matching so
the test suite runs instantly without any network calls or API keys.
This implements the Reasoner Protocol from zem.contracts.models.
"""

from __future__ import annotations

import time
from typing import Literal

from zem.contracts.models import IntelResult, JudgeVerdict, ToolCallContext

# Keywords in arguments that the mock will always flag as "deny"
_DENY_KEYWORDS = (
    "passwd",
    ".env",
    "shadow",
    "id_rsa",
    "curl",
    "wget",
    "eval",
    "exec",
    "evil",
    "exfil",
)

# Keywords that the mock will flag as "escalate" (uncertain — needs deep judge)
_ESCALATE_KEYWORDS = (
    "install",
    "upload",
    "send_email",
    "smtp",
    "post",
)


class MockReasoner:
    """Deterministic stand-in for the real Nebius/Nemotron reasoner.

    Behaviour:
    - Any tool argument containing a _DENY_KEYWORD → verdict: deny (confidence 0.99)
    - Any tool argument containing an _ESCALATE_KEYWORD → verdict: escalate (0.55)
    - Everything else → verdict: allow (confidence 0.95)

    This is intentionally simple.  The real NebiusReasoner will have
    sophisticated prompt engineering; this mock just needs to let the
    pipeline plumbing be tested end-to-end without hitting an API.
    """

    model_id: str = "mock-reasoner-v1"

    async def judge(
        self,
        ctx: ToolCallContext,
        *,
        depth: Literal["fast", "deep"],
        intel: IntelResult | None = None,
    ) -> JudgeVerdict:
        start = time.monotonic()

        # Flatten all argument values into one lowercase string for scanning
        args_blob = " ".join(str(v) for v in ctx.arguments.values()).lower()

        # Check for hard-deny keywords first
        for kw in _DENY_KEYWORDS:
            if kw in args_blob:
                return JudgeVerdict(
                    verdict="deny",
                    confidence=0.99,
                    reason=f"[mock] Argument contains suspicious keyword '{kw}'.",
                    risk_tags=["mock_deny", kw],
                    needs_intel=False,
                    model_id=self.model_id,
                    latency_ms=int((time.monotonic() - start) * 1000),
                )

        # Check for escalate keywords (gray-zone)
        for kw in _ESCALATE_KEYWORDS:
            if kw in args_blob or kw in ctx.tool.lower():
                return JudgeVerdict(
                    verdict="escalate",
                    confidence=0.55,
                    reason=f"[mock] Tool or argument contains ambiguous keyword '{kw}'. Escalate to deep judge.",
                    risk_tags=["mock_escalate", kw],
                    needs_intel=depth == "fast",  # request intel only on fast path
                    intel_query=f"Is '{ctx.tool}' with these args malicious?",
                    model_id=self.model_id,
                    latency_ms=int((time.monotonic() - start) * 1000),
                )

        # Default: allow
        return JudgeVerdict(
            verdict="allow",
            confidence=0.95,
            reason="[mock] No suspicious patterns detected.",
            risk_tags=[],
            needs_intel=False,
            model_id=self.model_id,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
