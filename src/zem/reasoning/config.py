"""Config + settings for the Nebius reasoner (R2-K3).

Model IDs live in config/models.yaml (roles, not names). The API key lives only in
the environment / a git-ignored .env file and is held as a SecretStr so it can
never leak through repr(), logs, or tracebacks.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "models.yaml"


class ConfigError(RuntimeError):
    """The model config is missing or invalid. Raised loudly; never guessed around."""


class RoleConfig(BaseModel):
    model: str = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0, le=2)
    timeout_s: float = Field(gt=0)
    enable_thinking: bool = False


class ModelsConfig(BaseModel):
    base_url: str = Field(min_length=1)
    roles: dict[str, RoleConfig]

    def role(self, name: str) -> RoleConfig:
        try:
            return self.roles[name]
        except KeyError:
            raise ConfigError(f"models.yaml has no role '{name}'") from None


class NebiusSettings(BaseSettings):
    """Reads NEBIUS_API_KEY from the environment or a local .env (git-ignored)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nebius_api_key: SecretStr | None = None


def load_models_config(path: Path | str | None = None) -> ModelsConfig:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        return ModelsConfig.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"cannot load model config {cfg_path}: {type(exc).__name__}") from exc

