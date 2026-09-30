"""Configuration: environment settings + business rules.

Two kinds of configuration, deliberately separated:

1. Settings (environment variables): secrets and deployment knobs.
   The API key lives ONLY here, is never logged and never repr()'d.
2. RulesConfig (config/rules.yaml): business decisions such as
   "policies go stale after 12 months". Changing trust rules must not
   require a code change, and must not require touching secrets.

Security notes:
- YAML is parsed with yaml.safe_load only. yaml.load can instantiate
  arbitrary Python objects from a crafted file (remote code execution).
- Both configs are validated at startup. Invalid config = the app refuses
  to start (fail closed), rather than running with half-applied rules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import ID_PATTERN, SourceType

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_CONFIG_BYTES = 256 * 1024


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid. The app must not start."""


# --------------------------------------------------------------------------
# Business rules (YAML)
# --------------------------------------------------------------------------


class RulesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Highest authority first.
    authority_order: tuple[SourceType, ...]
    max_age_days: dict[SourceType, int]
    handover_window_days: int = Field(ge=1, le=365)
    retrieval_top_k: int = Field(ge=1, le=20)
    max_content_chars_per_source: int = Field(ge=200, le=20_000)
    # Documents do not carry a type in their front matter; map them here.
    doc_type_by_id: dict[str, SourceType] = Field(default_factory=dict)
    # Role keywords in order of preference when routing to an expert.
    escalation_role_priority: tuple[str, ...] = ()

    @field_validator("authority_order")
    @classmethod
    def _complete_order(cls, v: tuple[SourceType, ...]) -> tuple[SourceType, ...]:
        missing = set(SourceType) - set(v)
        if missing:
            raise ValueError(f"authority_order is missing: {sorted(m.value for m in missing)}")
        if len(set(v)) != len(v):
            raise ValueError("authority_order contains duplicates")
        return v

    @field_validator("max_age_days")
    @classmethod
    def _positive_ages(cls, v: dict[SourceType, int]) -> dict[SourceType, int]:
        if any(days <= 0 for days in v.values()):
            raise ValueError("max_age_days values must be positive")
        return v

    def authority_rank(self, source_type: SourceType) -> int:
        """Lower number = more authoritative."""
        return self.authority_order.index(source_type)


def load_rules(path: Path) -> RulesConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"Rules file not found: {path}")
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ConfigError("Rules file is too large")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))  # never yaml.load
        return RulesConfig.model_validate(raw)
    except (yaml.YAMLError, ValueError) as exc:
        raise ConfigError(f"Invalid rules file: {exc}") from exc


# --------------------------------------------------------------------------
# Environment settings
# --------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, low: int, high: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not low <= parsed <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return parsed


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    rules_path: Path
    demo_user: str
    demo_country: str
    as_of_date: date
    gemini_model: str
    llm_timeout_seconds: int
    rate_limit_per_minute: int
    enable_api_docs: bool
    # repr=False: the key never appears in logs, tracebacks or debug prints.
    gemini_api_key: str | None = field(default=None, repr=False)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key)


def load_settings() -> Settings:
    import re

    user = os.getenv("TRUSTLENS_DEMO_USER", "arne.goossens")
    country = os.getenv("TRUSTLENS_DEMO_COUNTRY", "BE")
    as_of_raw = os.getenv("TRUSTLENS_AS_OF_DATE", "2026-09-30")

    if not re.fullmatch(ID_PATTERN, user):
        raise ConfigError("TRUSTLENS_DEMO_USER has invalid characters")
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ConfigError("TRUSTLENS_DEMO_COUNTRY must be a 2-letter code")
    try:
        as_of = date.fromisoformat(as_of_raw)
    except ValueError as exc:
        raise ConfigError("TRUSTLENS_AS_OF_DATE must be YYYY-MM-DD") from exc

    api_key = os.getenv("GEMINI_API_KEY") or None
    if api_key and api_key.strip() in {"", "your-key-here", "changeme"}:
        api_key = None  # placeholder from .env.example: treat as "no key"

    return Settings(
        data_dir=Path(os.getenv("TRUSTLENS_DATA_DIR", PROJECT_ROOT / "data")),
        rules_path=Path(os.getenv("TRUSTLENS_RULES_PATH", PROJECT_ROOT / "config" / "rules.yaml")),
        demo_user=user,
        demo_country=country,
        as_of_date=as_of,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        llm_timeout_seconds=_env_int("LLM_TIMEOUT_SECONDS", 20, 1, 120),
        rate_limit_per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 20, 1, 1000),
        enable_api_docs=_env_bool("ENABLE_API_DOCS", False),
        gemini_api_key=api_key,
    )
