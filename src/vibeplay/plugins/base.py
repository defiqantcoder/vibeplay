"""Modular plugin architecture and loader interface for VibePlay add-ons.

Decouples non-essential features (DSP, spatial audio, maintenance tools, enrichment)
from the lean core audio loop and local database engine.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PluginMetadata:
    """Metadata describing a VibePlay add-on/plugin."""

    name: str
    version: str = "0.2.0"
    description: str = ""
    author: str = "VibePlay Contributors"
    enabled: bool = True
    tags: list[str] = field(default_factory=list)


class Plugin(ABC):
    """Abstract base class for all VibePlay add-on plugins."""

    def __init__(self, metadata: PluginMetadata | None = None) -> None:
        self.metadata = metadata or PluginMetadata(name=self.__class__.__name__)
        self._is_initialized: bool = False

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def is_enabled(self) -> bool:
        return self.metadata.enabled

    def enable(self) -> None:
        """Enable the plugin."""
        self.metadata.enabled = True
        if not self._is_initialized:
            self.initialize()

    def disable(self) -> None:
        """Disable the plugin and release resources."""
        self.metadata.enabled = False
        if self._is_initialized:
            self.shutdown()

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the plugin components."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Tear down and clean up plugin resources."""
        pass

    def to_dict(self) -> dict[str, Any]:
        """Serialize plugin status and metadata."""
        return {
            "name": self.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "enabled": self.is_enabled,
            "tags": self.metadata.tags,
            "initialized": self._is_initialized,
        }


class PluginRegistry:
    """Singleton registry managing loaded plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a new plugin instance."""
        self._plugins[plugin.name] = plugin
        if plugin.is_enabled:
            try:
                plugin.initialize()
            except Exception as err:
                logger.error("Failed to initialize plugin '%s': %s", plugin.name, err)

    def unregister(self, name: str) -> None:
        """Unregister and shutdown a plugin."""
        if name in self._plugins:
            plugin = self._plugins.pop(name)
            try:
                plugin.shutdown()
            except Exception as err:
                logger.error("Error shutting down plugin '%s': %s", name, err)

    def get(self, name: str) -> Plugin | None:
        """Retrieve a registered plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return status dictionaries of all registered plugins."""
        return [p.to_dict() for p in self._plugins.values()]

    def is_enabled(self, name: str) -> bool:
        """Check if a registered plugin is active."""
        p = self.get(name)
        return p.is_enabled if p else False


_REGISTRY: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    """Get or create the global plugin registry."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = PluginRegistry()
    return _REGISTRY
