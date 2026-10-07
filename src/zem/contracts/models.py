from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0.0"


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REDACT = "redact"
    REQUIRE_APPROVAL = "require_approval"


class Severity(str, Enum):  # CHANGED: one member per line (ruff-friendly)
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Label(str, Enum):  # used from R4
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    SECRET_BEARING = "secret_bearing"


class ToolDefinition(BaseModel):  # used from R3 (pinning)
    server: str
    name: str
    description: str
    input_schema: dict[str, Any] = {}
    definition_hash: str


class Signal(BaseModel):
    detector: str
    code: str
    weight: float = Field(ge=0, le=1)
    severity: Severity = Severity.MEDIUM
    evidence: str  # short, human-readable, already redacted
    hard_deny: bool = False


class ToolCallContext(BaseModel):
    schema_version: str = SCHEMA_VERSION
    call_id: str
    session_id: str
    ts: datetime
    server: str
    tool: str
    arguments: dict[str, Any] = {}
    tool_def: ToolDefinition | None = None  # R3
    objective: str | None = None  # R4
    session_labels: list[Label] = []  # R4
    recent_calls: list[dict[str, Any]] = []  # R2
    signals: list[Signal] = []


class ToolResultContext(BaseModel):  # CHANGED: NEW. R3 egress filter needs a result shape
    call_id: str
    session_id: str
    server: str
    tool: str
    content: list[dict[str, Any]] = []  # MCP content blocks
    is_error: bool = False
    signals: list[Signal] = []


class JudgeVerdict(BaseModel):  # R2
    verdict: Literal["allow", "deny", "escalate"]
    confidence: float = Field(ge=0, le=1)
    reason: str  # <= 400 chars
    risk_tags: list[str] = []
    needs_intel: bool = False
    intel_query: str | None = None
    model_id: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0


class IntelItem(BaseModel):  # R3
    title: str
    url: str
    snippet: str
    score: float = 0.0


class IntelResult(BaseModel):  # R3
    query: str
    items: list[IntelItem] = []
    cached: bool = False
    latency_ms: int = 0


class FinalDecision(BaseModel):
    decision: Decision
    risk: float = Field(ge=0, le=1)
    reasons: list[str] = []
    redactions: list[str] = []


class AuditEvent(BaseModel):
    seq: int
    ts: datetime
    session_id: str
    call_id: str
    context: ToolCallContext
    judge: JudgeVerdict | None = None  # R2
    intel: IntelResult | None = None  # R3
    final: FinalDecision
    latency_breakdown_ms: dict[str, int] = {}
    prev_hash: str = ""  # R3
    this_hash: str = ""


# ---- Interfaces: the only seams between the two halves ----


class Detector(Protocol):
    name: str

    def inspect(self, ctx: ToolCallContext) -> list[Signal]: ...


class Reasoner(Protocol):
    async def judge(
        self,
        ctx: ToolCallContext,
        *,
        depth: Literal["fast", "deep"],
        intel: IntelResult | None = None,
    ) -> JudgeVerdict: ...


class Enricher(Protocol):
    async def lookup(self, query: str) -> IntelResult: ...


class AuditSink(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def verify_chain(self) -> bool: ...
