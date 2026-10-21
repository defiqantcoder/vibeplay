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
    enrichment_confidence_threshold: float = Field(
        default=0.8,
        description="Confidence threshold below which matches are marked as 'needs review'",
    )
    musicbrainz_app: str = Field(
        default="vibeplay",
        description="Application name for MusicBrainz User-Agent",
    )
    musicbrainz_version: str = Field(
        default="0.1.0",
        description="Application version for MusicBrainz User-Agent",
    )
    musicbrainz_contact: str = Field(
        default="https://github.com/defiqantcoder/vibeplay",
        description="Contact URL for MusicBrainz User-Agent",
    )
    musicbrainz_rate_limit: float = Field(
        default=1.0,
        description="Minimum seconds between MusicBrainz requests",
    )
    network_max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for network requests",
    )
    network_backoff_factor: float = Field(
        default=2.0,
        description="Backoff factor for exponential retry delays",
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
