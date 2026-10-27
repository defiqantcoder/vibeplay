"""Plugin Manager for discovering and controlling VibePlugins."""

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

from vibeplay.plugins.base import VibePlugin

logger = logging.getLogger(__name__)


class PluginManager:
    """Discovers, loads, and manages lifecycle of VibePlugins."""

    def __init__(self, app: Any = None):
        self.app = app
        self.plugins: dict[str, VibePlugin] = {}
        self.active_plugins: set[str] = set()
        self.plugin_configs: dict[str, dict[str, Any]] = {}
        self.plugin_metadata: dict[str, dict[str, Any]] = {}

        self.builtin_dir = Path(__file__).parent / "builtin"
        self.user_dir = Path.home() / ".config" / "vibeplay" / "plugins"

    def initialize(self):
        """Discover and load plugins."""
        self._ensure_user_dir()
        self._discover_plugins(self.builtin_dir)
        self._discover_plugins(self.user_dir)

    def _ensure_user_dir(self):
        """Ensure user plugin directory exists with 0700 permissions."""
        if not self.user_dir.exists():
            self.user_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.user_dir, 0o700)

        # Check permissions
        stat = os.stat(self.user_dir)
        if stat.st_mode & 0o777 != 0o700:
            logger.warning(f"Plugin directory {self.user_dir} has insecure permissions. Enforcing 0700.")
            os.chmod(self.user_dir, 0o700)

    def _discover_plugins(self, directory: Path):
        """Discover plugins in a given directory."""
        if not directory.exists() or not directory.is_dir():
            return

        for path in directory.iterdir():
            if path.is_file() and path.suffix == ".py" and path.name != "__init__.py":
                self._load_plugin_module(path)
            elif path.is_dir() and (path / "__init__.py").exists():
                self._load_plugin_module(path / "__init__.py")

    def _load_plugin_module(self, path: Path):
        """Safely load a python module and instantiate plugins."""
        module_name = f"vibeplay.plugins.loaded.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec and spec.loader:
            try:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # Find classes inheriting from VibePlugin
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, VibePlugin) and attr is not VibePlugin:
                        plugin_instance = attr()
                        manifest = plugin_instance.get_manifest()
                        plugin_id = manifest.get("id")
                        if plugin_id:
                            self.plugins[plugin_id] = plugin_instance
                            self.plugin_metadata[plugin_id] = manifest
                            logger.info(f"Loaded plugin: {plugin_id}")
            except Exception as e:
                logger.error(f"Failed to load plugin from {path}: {e}")

    def toggle_plugin(self, plugin_id: str, enable: bool) -> bool:
        """Toggle a plugin on or off."""
        if plugin_id not in self.plugins:
            return False

        if enable and plugin_id not in self.active_plugins:
            plugin = self.plugins[plugin_id]
            try:
                config = self.plugin_configs.get(plugin_id, {})
                plugin.on_load(self.app, config)
                self.active_plugins.add(plugin_id)
                return True
            except Exception as e:
                logger.error(f"Error enabling plugin {plugin_id}: {e}")
                return False
        elif not enable and plugin_id in self.active_plugins:
            plugin = self.plugins[plugin_id]
            try:
                plugin.on_unload()
            except Exception as e:
                logger.error(f"Error unloading plugin {plugin_id}: {e}")
            finally:
                self.active_plugins.remove(plugin_id)
                return True
        return True

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return a list of all plugins with their active state."""
        result = []
        for plugin_id, manifest in self.plugin_metadata.items():
            info = manifest.copy()
            info["active"] = plugin_id in self.active_plugins
            result.append(info)
        return result

    def get_plugin_config(self, plugin_id: str) -> dict[str, Any]:
        """Get the current configuration for a plugin."""
        return self.plugin_configs.get(plugin_id, {})

    def set_plugin_config(self, plugin_id: str, config: dict[str, Any]):
        """Set the configuration for a plugin."""
        self.plugin_configs[plugin_id] = config
        # If active, might need to reload, but we'll leave that to the caller

    # Lifecycle Event Dispatchers
    def _dispatch_event(self, event_name: str, *args, **kwargs):
        """Safely dispatch an event to all active plugins."""
        for plugin_id in self.active_plugins:
            plugin = self.plugins.get(plugin_id)
            if plugin:
                method = getattr(plugin, event_name, None)
                if method and callable(method):
                    try:
                        method(*args, **kwargs)
                    except Exception as e:
                        logger.error(f"Plugin {plugin_id} failed on {event_name}: {e}")

    def on_track_start(self, track_metadata: dict[str, Any]):
        """Dispatch track start event."""
        self._dispatch_event("on_track_start", track_metadata)

    def on_track_end(self, track_metadata: dict[str, Any]):
        """Dispatch track end event."""
        self._dispatch_event("on_track_end", track_metadata)


_MANAGER_INSTANCE: PluginManager | None = None


def get_plugin_manager(app: Any = None) -> PluginManager:
    """Get the global plugin manager instance."""
    global _MANAGER_INSTANCE
    if _MANAGER_INSTANCE is None:
        _MANAGER_INSTANCE = PluginManager(app)
    return _MANAGER_INSTANCE
