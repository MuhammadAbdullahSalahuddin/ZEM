from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

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
