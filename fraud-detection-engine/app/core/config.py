"""Application settings and validated per-bank YAML configuration loading."""

from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from math import isfinite
from pathlib import Path
import re
from typing import cast

from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml


BankConfig = dict[str, object]
_BANK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class BankConfigError(ValueError):
    """Raised when a bank ID is invalid or its YAML configuration is malformed."""


class Settings(BaseSettings):
    """Runtime configuration for the scoring service."""

    model_config = SettingsConfigDict(env_prefix="FRAUD_", env_file=".env", extra="ignore")

    app_name: str = "Fraud Detection Engine"
    environment: str = "development"
    api_key: str = "dev-only-change-me"
    bank_config_path: str = "configs/banks/default.yaml"
    bank_config_dir: str = "configs/banks"
    fraud_threshold: float = 0.7


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()


class BankConfigLoader:
    """Load bank-specific settings from local YAML files.

    A missing or empty bank ID selects ``default.yaml``. An unknown explicit
    bank ID raises ``FileNotFoundError`` instead of silently using another
    bank's fraud policy.
    """

    def __init__(self, config_dir: str | Path | None = None) -> None:
        configured_dir = Path(config_dir or get_settings().bank_config_dir).expanduser()
        if not configured_dir.is_absolute():
            configured_dir = Path(__file__).resolve().parents[2] / configured_dir
        self.config_dir = configured_dir.resolve()

    def load(self, bank_id: str | None = None) -> BankConfig:
        """Return a validated copy of the selected bank configuration."""
        normalized_bank_id = (bank_id or "default").strip() or "default"
        if not _BANK_ID_PATTERN.fullmatch(normalized_bank_id):
            raise BankConfigError("bank_id may contain only letters, digits, underscores, and hyphens")

        path = (self.config_dir / f"{normalized_bank_id}.yaml").resolve()
        if path.parent != self.config_dir:
            raise BankConfigError("Bank configuration path must remain inside the banks directory")
        if not path.is_file():
            raise FileNotFoundError(f"Configuration for bank '{normalized_bank_id}' not found: {path}")
        return deepcopy(_load_yaml_config(path))


@lru_cache(maxsize=64)
def _load_yaml_config(path: Path) -> BankConfig:
    """Read and validate a YAML file once; callers receive independent copies."""
    try:
        with path.open(encoding="utf-8") as config_file:
            raw_config = yaml.safe_load(config_file)
    except yaml.YAMLError as exc:
        raise BankConfigError(f"Invalid YAML in bank configuration {path}: {exc}") from exc

    if not isinstance(raw_config, Mapping):
        raise BankConfigError(f"Bank configuration must contain a YAML mapping: {path}")
    config = cast(BankConfig, dict(raw_config))
    _validate_bank_config(config, path)
    return config


def _validate_bank_config(config: BankConfig, path: Path) -> None:
    """Validate fields required by scoring before accepting a bank policy."""
    thresholds = config.get("thresholds")
    if not isinstance(thresholds, Mapping):
        raise BankConfigError(f"'thresholds' must be a mapping in {path}")

    values: dict[str, float] = {}
    for key in ("approve_max", "review_max", "decline_min"):
        raw_value = thresholds.get(key)
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise BankConfigError(f"thresholds.{key} must be a number in {path}")
        value = float(raw_value)
        if not isfinite(value) or not 0 <= value <= 1:
            raise BankConfigError(f"thresholds.{key} must be between 0 and 1 in {path}")
        values[key] = value

    if not values["approve_max"] < values["review_max"] <= values["decline_min"]:
        raise BankConfigError(
            f"thresholds must satisfy approve_max < review_max <= decline_min in {path}"
        )
    if not isinstance(config.get("rules"), Mapping):
        raise BankConfigError(f"'rules' must be a mapping in {path}")


def load_bank_config(bank_id: str | None = None) -> BankConfig:
    """Convenience function to load a bank config using the configured folder."""
    return BankConfigLoader().load(bank_id)
