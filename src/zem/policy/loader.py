from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"


class PolicyError(Exception):
    pass


class ToolRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow: list[str] | None = None  # None = every tool allowed
    deny: list[str] = []


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fast_judge: float = 0.30
    deep_judge: float = 0.60
    deny: float = 0.85

    @model_validator(mode="after")
    def _ordered(self) -> Thresholds:
        if not (0 < self.fast_judge < self.deep_judge < self.deny <= 1):
            raise ValueError("need 0 < fast_judge < deep_judge < deny <= 1")
        return self


class JudgeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False  # False = pure R1 behaviour. The R2 switch.
    min_confidence: float = 0.7
    timeout_s: float = 6.0
    deep_enabled: bool = False  # R3 turns this on


class Budgets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_judge_per_session: int = 15
    max_judge_global: int = 200

EgressAction = Literal["redact", "flag", "block", "off"]
PACKS = ("secrets", "pii_ids", "contact", "injection")
MAX_CUSTOM_PATTERN = 200
# Catches the classic freeze-ZEM shapes like (a+)+ or (.*)*. A heuristic, not a proof.
_NESTED_QUANTIFIER = re.compile(r"\([^)]*[+*][^)]*\)[+*{]")


class CustomEgressRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    pattern: str
    action: EgressAction = "redact"

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", v):
            raise ValueError("name must be lower_snake_case, at most 40 characters")
        if v in PACKS:
            raise ValueError(f"'{v}' is a built-in pack name")
        return v

    @field_validator("pattern")
    @classmethod
    def _pattern_ok(cls, v: str) -> str:
        if not v or len(v) > MAX_CUSTOM_PATTERN:
            raise ValueError(f"pattern must be 1-{MAX_CUSTOM_PATTERN} characters")
        if _NESTED_QUANTIFIER.search(v):
            raise ValueError("pattern has nested repetition and could freeze ZEM")
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v


class EgressException(BaseModel):
    """This tool is SUPPOSED to return this kind of data, so skip these rules for it."""

    model_config = ConfigDict(extra="forbid")
    tool: str
    allow: list[str]


class EgressSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    secrets: EgressAction = "redact"
    pii_ids: EgressAction = "redact"
    contact: EgressAction = "flag"
    injection: EgressAction = "flag"
    custom: list[CustomEgressRule] = []
    exceptions: list[EgressException] = []
    max_scan_chars: int = Field(default=2_000_000, gt=0)

    @model_validator(mode="after")
    def _consistent(self) -> EgressSettings:
        names = [r.name for r in self.custom]
        if len(set(names)) != len(names):
            raise ValueError("duplicate custom egress rule names")
        known = set(PACKS) | set(names)
        for exc in self.exceptions:
            unknown = [a for a in exc.allow if a not in known]
            if unknown:
                raise ValueError(f"exception for '{exc.tool}' names unknown rules: {unknown}")
        return self

class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in YAML must fail, not be ignored
    name: str
    allowed_roots: list[str] = ["."]
    tools: ToolRules = ToolRules()
    net_allowlist: list[str] = []
    hard_deny_codes: list[str] = []  # soft signal codes promoted to hard deny
    thresholds: Thresholds = Thresholds()
    judge: JudgeSettings = JudgeSettings()
    budgets: Budgets = Budgets()
    on_error: Literal["fail_closed", "fail_open", "fail_closed_for_write"] = (
        "fail_closed_for_write"
    )
    read_only_tools: list[str] = []  # extra tool names treated as read-only
    known_packages: list[str] = []  # your project's own dependencies 
    egress: EgressSettings = EgressSettings()
def load_policy(ref: str) -> Policy:
    is_path = ref.endswith((".yaml", ".yml")) or "/" in ref
    path = Path(ref) if is_path else POLICY_DIR / f"{ref}.yaml"
    if not path.is_file():
        raise PolicyError(f"policy not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise PolicyError(f"policy {path} must be a YAML mapping")
        return Policy.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        raise PolicyError(f"invalid policy {path}: {exc}") from exc
