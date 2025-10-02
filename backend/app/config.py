from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application runtime configuration."""

    app_name: str = Field(default="interviewer-agent-backend", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    database_url: str = Field(default="sqlite+aiosqlite:///./interviewer.db", alias="DATABASE_URL")
    allow_origins_raw: str | None = Field(default=None, alias="ALLOW_ORIGINS")
    asr_upstream_url: str | None = Field(default=None, alias="ASR_UPSTREAM_URL")
    tts_upstream_url: str | None = Field(default=None, alias="TTS_UPSTREAM_URL")
    llm_upstream_url: str | None = Field(default=None, alias="LLM_UPSTREAM_URL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def allow_origins(self) -> List[str]:
        if not self.allow_origins_raw:
            return ["http://localhost:5173", "http://127.0.0.1:5173"]
        return [origin.strip() for origin in self.allow_origins_raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
