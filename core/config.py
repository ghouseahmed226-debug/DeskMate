"""Application configuration powered by Pydantic Settings."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

_PLACEHOLDER_PREFIXES = ("replace-with-", "changeme", "your-", "placeholder")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="DeskMate AI", alias="APP_NAME")
    app_version: str = Field(default="2.0.0", alias="APP_VERSION")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    secret_key: str = Field(default="", alias="SECRET_KEY")
    encryption_key: str = Field(default="", alias="ENCRYPTION_KEY")
    jwt_expire_minutes: int = Field(default=120, alias="JWT_EXPIRE_MINUTES")
    allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="ALLOWED_ORIGINS",
    )

    database_url: str = Field(
        default=f"sqlite:///{(BASE_DIR / 'deskmate.db').as_posix()}",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    storage_backend: str = Field(default="database", alias="STORAGE_BACKEND")

    llm_provider: str = Field(default="offline", alias="LLM_PROVIDER")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    llm_model: str = Field(default="", alias="LLM_MODEL")

    deskmate_use_adk: bool = Field(default=False, alias="DESKMATE_USE_ADK")
    mcp_transport: str = Field(default="stdio", alias="MCP_TRANSPORT")

    rate_limit_per_min: int = Field(default=60, alias="RATE_LIMIT_PER_MIN")
    anomaly_time_window_sec: int = Field(default=60, alias="ANOMALY_TIME_WINDOW_SEC")
    anomaly_max_calls_per_min: int = Field(default=10, alias="ANOMALY_MAX_CALLS_PER_MIN")
    anomaly_max_consecutive_writes: int = Field(
        default=3, alias="ANOMALY_MAX_CONSECUTIVE_WRITES"
    )
    default_timezone: str = Field(default="UTC", alias="DEFAULT_TIMEZONE")

    google_client_id: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/integrations/google/callback",
        alias="GOOGLE_REDIRECT_URI",
    )
    slack_client_id: str = Field(default="", alias="SLACK_CLIENT_ID")
    slack_client_secret: str = Field(default="", alias="SLACK_CLIENT_SECRET")
    notion_client_id: str = Field(default="", alias="NOTION_CLIENT_ID")
    notion_client_secret: str = Field(default="", alias="NOTION_CLIENT_SECRET")
    github_client_id: str = Field(default="", alias="GITHUB_CLIENT_ID")
    github_client_secret: str = Field(default="", alias="GITHUB_CLIENT_SECRET")
    microsoft_client_id: str = Field(default="", alias="MICROSOFT_CLIENT_ID")
    microsoft_client_secret: str = Field(default="", alias="MICROSOFT_CLIENT_SECRET")

    @field_validator("app_env")
    @classmethod
    def normalize_env(cls, v: str) -> str:
        val = (v or "development").strip().lower()
        if val not in {"development", "test", "production", "staging"}:
            return "development"
        return val

    def validate_runtime_secrets(self) -> None:
        is_prod = self.app_env == "production"
        if not self.secret_key or self.secret_key.lower().startswith(_PLACEHOLDER_PREFIXES):
            if is_prod:
                raise RuntimeError("SECRET_KEY must be set to a strong value in production.")
            self.secret_key = secrets.token_urlsafe(48)

        if not self.encryption_key or self.encryption_key.lower().startswith(_PLACEHOLDER_PREFIXES):
            if is_prod:
                raise RuntimeError("ENCRYPTION_KEY must be a valid Fernet key in production.")
            digest = hashlib.sha256(self.secret_key.encode("utf-8")).digest()
            self.encryption_key = base64.urlsafe_b64encode(digest).decode("ascii")

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def data_dir(self) -> Path:
        return BASE_DIR / "mock_data"

    @property
    def audit_log_path(self) -> Path:
        return BASE_DIR / "audit_log.jsonl"

    @property
    def upload_dir(self) -> Path:
        path = BASE_DIR / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime_secrets()
    return settings
