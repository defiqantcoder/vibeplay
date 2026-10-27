"""Modular plugin architecture and loader interface for VibePlay add-ons.

Decouples non-essential features (DSP, spatial audio, maintenance tools, enrichment)
from the lean core audio loop and local database engine.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class VibePlugin(ABC):
    """Abstract base class for all VibePlay add-on plugins."""

    @abstractmethod
    def get_manifest(self) -> dict[str, Any]:
        """Return plugin manifest.

        Must include:
        - id: str
        - name: str
        - description: str
        - author: str
        - version: str
        - icon: str
        - settings_schema: dict
        """
        pass

    def on_load(self, app: Any, config: dict[str, Any]) -> None:
        """Initialize the plugin components."""
        pass

    def on_unload(self) -> None:
        """Tear down and clean up plugin resources."""
        pass

    def on_track_start(self, track_metadata: dict[str, Any]) -> None:
        """Called when a track starts playing."""
        pass

    def on_track_end(self, track_metadata: dict[str, Any]) -> None:
        """Called when a track finishes playing."""
        pass
