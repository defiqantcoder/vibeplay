"""Sample Built-in LastFM Scrobbler Plugin."""

import logging
from typing import Any

from vibeplay.plugins.base import VibePlugin

logger = logging.getLogger(__name__)


class LastFmScrobblerPlugin(VibePlugin):
    """A lightweight Last.fm scrobbler plugin."""

    def __init__(self):
        self.session_key = None
        self.is_loaded = False

    def get_manifest(self) -> dict[str, Any]:
        return {
            "id": "lastfm-scrobbler",
            "name": "Last.fm Scrobbler",
            "description": "Scrobbles tracks to Last.fm.",
            "author": "VibePlay Contributors",
            "version": "1.0.0",
            "icon": "🎵",
            "settings_schema": {"session_key": {"type": "string", "title": "Session Key", "description": "API session key for Last.fm"}},
        }

    def on_load(self, app: Any, config: dict[str, Any]) -> None:
        self.session_key = config.get("session_key")
        self.is_loaded = True
        logger.info(f"Last.fm Scrobbler plugin loaded with key: {self.session_key}")

    def on_unload(self) -> None:
        self.session_key = None
        self.is_loaded = False
        logger.info("Last.fm Scrobbler plugin unloaded")

    def on_track_start(self, track_metadata: dict[str, Any]) -> None:
        if not self.is_loaded or not self.session_key:
            return
        # Simulate updating now playing
        title = track_metadata.get("title", "Unknown Title")
        artist = track_metadata.get("artist", "Unknown Artist")
        logger.info(f"[Last.fm] Now Playing: {artist} - {title}")

    def on_track_end(self, track_metadata: dict[str, Any]) -> None:
        if not self.is_loaded or not self.session_key:
            return
        # Simulate scrobbling
        title = track_metadata.get("title", "Unknown Title")
        artist = track_metadata.get("artist", "Unknown Artist")
        logger.info(f"[Last.fm] Scrobbled: {artist} - {title}")
