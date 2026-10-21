"""Configuration management for vibeplay using Pydantic Settings."""

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_path: Path = Field(
        default_factory=lambda: Path("~/.local/share/vibeplay/vibeplay.db").expanduser(),
        description="Path to SQLite database file",
    )
    acoustid_api_key: str | None = Field(
        default=None,
        description="AcoustID API key for metadata fingerprinting",
    )
    gemini_api_key: str | None = Field(
        default=None,
        description="API key for optional Gemini LLM integration",
    )
    vibeplay_env: str = Field(
        default="development",
        description="Environment name (development, testing, production)",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve and cache application configuration.

    Returns:
        Settings: Validated application configuration instance.
    """
    settings = Settings()
    logger.debug("Loaded settings for environment: %s", settings.vibeplay_env)
    return settings
