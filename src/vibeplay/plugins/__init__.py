"""VibePlay Plugins and Add-ons Subsystem.

Provides pluggable extensions that can be toggled without interfering with
the lean bit-perfect audio core.
"""

from __future__ import annotations

from vibeplay.plugins.base import (
    Plugin,
    PluginMetadata,
    PluginRegistry,
    get_plugin_registry,
)

__all__ = [
    "Plugin",
    "PluginMetadata",
    "PluginRegistry",
    "get_plugin_registry",
]
