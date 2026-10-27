"""VibePlay Plugins and Add-ons Subsystem.

Provides pluggable extensions that can be toggled without interfering with
the lean bit-perfect audio core.
"""

from __future__ import annotations

from vibeplay.plugins.base import VibePlugin
from vibeplay.plugins.manager import PluginManager, get_plugin_manager

__all__ = ["VibePlugin", "PluginManager", "get_plugin_manager"]
