"""Application configuration loaded from environment variables and .env files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime settings.

    Secrets are represented as plain strings only inside the process. They must
    never be logged or returned by an API.
    """

    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TaskPilot"
    app_version: str = "2.0.0"
    environment: str = "development"
    database_url: str = "sqlite:///./data/taskpilot.db"
    database_auto_migrate: bool = True
    app_timezone: str = "Asia/Shanghai"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    agent_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    agent_max_retries: int = Field(default=1, ge=0, le=3)
    agent_recursion_limit: int = Field(default=10, ge=3, le=30)
    pending_action_ttl_minutes: int = Field(default=30, ge=1, le=1440)

    @field_validator("app_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value

    @field_validator("deepseek_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("DEEPSEEK_BASE_URL must start with http:// or https://")
        return value

    @field_validator("deepseek_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("DEEPSEEK_MODEL must not be empty")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def agent_enabled(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
