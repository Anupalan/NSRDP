"""Runtime settings and policy configuration.

Settings come from environment variables (prefix ``NSRDP_``). Policy that the REOI leaves
TBC (tenant levels, roles, segregation-of-duties pairs, ...) lives in YAML files under
``NSRDP_CONFIG_DIR`` so it can change without a code change.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NSRDP_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///:memory:"
    config_dir: Path = Path(__file__).resolve().parents[2] / "config"
    environment: str = "local"
    auth_mode: Literal["disabled", "dev"] = "disabled"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_policy(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Load ``<config_dir>/<name>.yaml``."""
    base = config_dir or get_settings().config_dir
    with open(base / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
