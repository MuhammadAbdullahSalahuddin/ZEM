from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"


class PolicyError(Exception):
    pass


class ToolRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow: list[str] | None = None  # None = every tool allowed
    deny: list[str] = []


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in YAML must fail, not be ignored
    name: str
    allowed_roots: list[str] = ["."]
    tools: ToolRules = ToolRules()
    net_allowlist: list[str] = []
    hard_deny_codes: list[str] = []  # soft signal codes promoted to hard deny


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
