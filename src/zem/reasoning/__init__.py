"""ZEM reasoning package (R2).

Exposes MockReasoner, NebiusReasoner, RecordReplayReasoner, and make_reasoner()
so the pipeline can switch via ZEM_REASONER=mock|nebius.
"""

from __future__ import annotations

import os

from zem.contracts.models import Reasoner
from zem.reasoning.config import ConfigError, ModelsConfig, load_models_config
from zem.reasoning.mock_reasoner import MockReasoner
from zem.reasoning.nebius_reasoner import NebiusReasoner
from zem.reasoning.record_replay import CassetteError, RecordReplayReasoner

__all__ = [
    "CassetteError",
    "ConfigError",
    "MockReasoner",
    "ModelsConfig",
    "NebiusReasoner",
    "RecordReplayReasoner",
    "load_models_config",
    "make_reasoner",
]


def make_reasoner(kind: str | None = None) -> Reasoner:
    """Instantiate the configured reasoner ('mock' or 'nebius').

    Reads ZEM_REASONER from the environment when `kind` is not provided,
    defaulting to 'mock' so offline runs and unit tests work out of the box.
    """
    choice = (kind or os.environ.get("ZEM_REASONER", "mock")).strip().lower()
    if choice == "mock":
        return MockReasoner()
    if choice == "nebius":
        return NebiusReasoner()
    raise ConfigError(f"unknown ZEM_REASONER={choice!r}; expected 'mock' or 'nebius'")

