"""Configuration loading and validation for X-Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str | Path) -> Path:
    """Resolve a config path relative to the project root."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


class ModelSettings(BaseModel):
    """Gemini model names used by the agent."""

    flash: str = "gemini-2.5-flash"
    pro: str = "gemini-2.5-pro"
    vision: str = "gemini-2.5-flash"


class GeminiSettings(BaseModel):
    """Gemini throttle and retry settings."""

    rpm_limit: int = Field(default=10, ge=1)
    rpd_limit: int = Field(default=250, ge=1)
    timeout_seconds: int = Field(default=60, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=2.0, ge=0.0)


class SafetySettings(BaseModel):
    """Non-bypassable publishing safety limits."""

    daily_post_cap: int = Field(default=3, ge=0)
    min_post_interval_minutes: int = Field(default=180, ge=1)
    oracle_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    oracle_score_threshold: float = Field(default=0.55, ge=0.0, le=1.0)


class BrowserSettings(BaseModel):
    """Human-speed browser session settings."""

    headless: bool = False
    session_min_seconds: int = Field(default=30, ge=1)
    session_max_seconds: int = Field(default=180, ge=1)
    action_jitter_min_seconds: float = Field(default=0.8, ge=0.0)
    action_jitter_max_seconds: float = Field(default=2.5, ge=0.0)

    @field_validator("session_max_seconds")
    @classmethod
    def validate_session_window(cls, value: int, info: Any) -> int:
        min_seconds = info.data.get("session_min_seconds")
        if min_seconds is not None and value < min_seconds:
            raise ValueError("session_max_seconds must be >= session_min_seconds")
        return value

    @field_validator("action_jitter_max_seconds")
    @classmethod
    def validate_jitter_window(cls, value: float, info: Any) -> float:
        min_seconds = info.data.get("action_jitter_min_seconds")
        if min_seconds is not None and value < min_seconds:
            raise ValueError("action_jitter_max_seconds must be >= action_jitter_min_seconds")
        return value


class PostingSettings(BaseModel):
    """Posting defaults used by CLI smoke checks."""

    test_post_text: str = Field(default="hello world", min_length=1, max_length=280)


class Settings(BaseModel):
    """Top-level application settings."""

    shadow_mode: bool = True
    database_path: str = "data/xagent.db"
    chrome_profile_dir: str = "chrome_profile"
    logs_dir: str = "logs"
    kill_switch_file: str = "data/KILL_SWITCH"
    models: ModelSettings = Field(default_factory=ModelSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    posting: PostingSettings = Field(default_factory=PostingSettings)

    @property
    def database_file(self) -> Path:
        """SQLite database path resolved against the project root."""
        return resolve_path(self.database_path)

    @property
    def chrome_profile_path(self) -> Path:
        """Persistent Chrome profile path resolved against the project root."""
        return resolve_path(self.chrome_profile_dir)

    @property
    def logs_path(self) -> Path:
        """Log directory path resolved against the project root."""
        return resolve_path(self.logs_dir)

    @property
    def kill_switch_path(self) -> Path:
        """Kill-switch file path resolved against the project root."""
        return resolve_path(self.kill_switch_file)


class BrandBible(BaseModel):
    """Brand constraints injected into generation and safety checks."""

    niche: str = Field(min_length=1)
    voice: dict[str, Any] = Field(default_factory=dict)
    themes: list[str] = Field(default_factory=list)
    no_go_topics: list[str] = Field(default_factory=list)
    goals: dict[str, Any] = Field(default_factory=dict)


class AppConfig(BaseModel):
    """Validated runtime config bundle."""

    settings: Settings
    brand_bible: BrandBible


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_config(
    settings_path: str | Path = "config/settings.yaml",
    brand_bible_path: str | Path = "config/brand_bible.yaml",
) -> AppConfig:
    """Load `.env`, validate YAML config, and ensure local directories exist."""
    load_dotenv(PROJECT_ROOT / ".env")
    settings = Settings.model_validate(_read_yaml(resolve_path(settings_path)))
    brand_bible = BrandBible.model_validate(_read_yaml(resolve_path(brand_bible_path)))

    settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    settings.chrome_profile_path.mkdir(parents=True, exist_ok=True)
    settings.logs_path.mkdir(parents=True, exist_ok=True)

    return AppConfig(settings=settings, brand_bible=brand_bible)
