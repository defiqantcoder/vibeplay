"""Configuration management for vibeplay using Pydantic Settings."""

import logging
import os
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
        default_factory=lambda: Path(
            "~/.local/share/vibeplay/vibeplay.db"
        ).expanduser(),
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
    models_dir: Path = Field(
        default_factory=lambda: Path("models").resolve(),
        description="Directory containing pretrained machine learning models",
    )
    analyzer_backend: str = Field(
        default="essentia",
        description="Default audio analyzer backend ('essentia' or 'librosa')",
    )
    analyzer_workers: int = Field(
        default_factory=lambda: max(1, (os.cpu_count() or 2) - 1),
        description="Default number of parallel worker processes for audio analysis",
    )
    analyzer_window_seconds: float = Field(
        default=60.0,
        description="Analysis window duration extracted from track middle (seconds)",
    )
    weight_bpm: float = Field(
        default=1.0,
        description="Weight for BPM tempo feature in vibe vector formulation",
    )
    weight_loudness: float = Field(
        default=0.5,
        description="Weight for integrated loudness feature in vibe vector formulation",
    )
    weight_danceability: float = Field(
        default=1.0,
        description="Weight for danceability feature in vibe vector formulation",
    )
    weight_energy: float = Field(
        default=1.0,
        description="Weight for energy feature in vibe vector formulation",
    )
    weight_mood: float = Field(
        default=1.0,
        description="Weight for mood probabilities in vibe vector formulation",
    )
    weight_embedding: float = Field(
        default=0.8,
        description="Weight for PCA-reduced embedding features in vibe vector formulation",
    )
    bpm_harmonic_weight: float = Field(
        default=0.8,
        description="Proportion of circular/harmonic BPM weight vs absolute BPM weight",
    )
    pca_embedding_dimensions: int = Field(
        default=16,
        description="Number of principal components for embedding dimensionality reduction",
    )
    vector_cache_dir: Path | None = Field(
        default=None,
        description="Directory for caching computed vibe vectors (defaults to database directory)",
    )
    clustering_default_k: int = Field(
        default=5,
        description="Default number of clusters for KMeans clustering",
    )
    clustering_default_algorithm: str = Field(
        default="kmeans",
        description="Default clustering algorithm ('kmeans' or 'hdbscan')",
    )
    playlist_default_limit: int = Field(
        default=25,
        description="Default maximum track count for generated playlists",
    )
    playlist_max_artist_tracks: int = Field(
        default=2,
        description="Default maximum allowed tracks by the same artist in a playlist",
    )
    mpd_host: str = Field(
        default="localhost",
        description="Hostname, IP address, or UNIX domain socket path for MPD daemon",
    )
    mpd_port: int = Field(
        default=6600,
        description="Port for Music Player Daemon (MPD) TCP connection",
    )
    mpd_timeout: float = Field(
        default=10.0,
        description="Timeout in seconds for MPD connection and commands",
    )
    export_default_format: str = Field(
        default="m3u8",
        description="Default playlist export format ('m3u8', 'm3u', 'json', or 'csv')",
    )

    def get_vector_cache_path(self, db_path: Path | None = None) -> Path:
        """Return the resolved path to the vector cache file."""
        if self.vector_cache_dir is not None:
            return self.vector_cache_dir / "vectors_cache.npz"
        base_dir = (db_path or self.db_path).parent
        return base_dir / "vectors_cache.npz"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retrieve and cache application configuration.

    Returns:
        Settings: Validated application configuration instance.
    """
    settings = Settings()
    logger.debug("Loaded settings for environment: %s", settings.vibeplay_env)
    return settings
