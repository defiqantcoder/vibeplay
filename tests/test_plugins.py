import os
import stat
import tempfile
from pathlib import Path

from vibeplay.plugins.base import VibePlugin
from vibeplay.plugins.builtin.lastfm import LastFmScrobblerPlugin
from vibeplay.plugins.manager import PluginManager


def test_vibe_plugin_base():
    """Test VibePlugin base class default behaviors."""

    class DummyPlugin(VibePlugin):
        def get_manifest(self):
            return {"id": "dummy"}

    plugin = DummyPlugin()
    assert plugin.get_manifest()["id"] == "dummy"
    # Should not raise
    plugin.on_load(None, {})
    plugin.on_track_start({})
    plugin.on_track_end({})
    plugin.on_unload()


def test_lastfm_scrobbler_plugin():
    """Test the built-in LastFM scrobbler plugin."""
    plugin = LastFmScrobblerPlugin()
    manifest = plugin.get_manifest()
    assert manifest["id"] == "lastfm-scrobbler"

    # Not loaded, shouldn't do anything (just asserting no exceptions)
    plugin.on_track_start({"title": "Test", "artist": "Tester"})

    plugin.on_load(None, {"session_key": "testkey"})
    assert plugin.session_key == "testkey"
    assert plugin.is_loaded

    # Loaded, simulating scrobbling
    plugin.on_track_start({"title": "Test", "artist": "Tester"})
    plugin.on_track_end({"title": "Test", "artist": "Tester"})

    plugin.on_unload()
    assert not plugin.is_loaded


def test_plugin_manager_discovery_and_toggles():
    """Test PluginManager discovering builtin plugins and toggling state."""
    manager = PluginManager(app=None)
    # We won't use the default user_dir to avoid touching ~/.config
    with tempfile.TemporaryDirectory() as td:
        user_path = Path(td) / "plugins"
        manager.user_dir = user_path

        manager.initialize()

        plugins_list = manager.list_plugins()
        ids = [p["id"] for p in plugins_list]

        assert "lastfm-scrobbler" in ids

        # Toggle on
        success = manager.toggle_plugin("lastfm-scrobbler", True)
        assert success

        pl = [p for p in manager.list_plugins() if p["id"] == "lastfm-scrobbler"][0]
        assert pl["active"] is True

        # Dispatch events
        manager.on_track_start({"title": "Track", "artist": "Art"})

        # Toggle off
        success = manager.toggle_plugin("lastfm-scrobbler", False)
        assert success

        pl = [p for p in manager.list_plugins() if p["id"] == "lastfm-scrobbler"][0]
        assert pl["active"] is False


def test_plugin_manager_user_dir_permissions():
    """Test PluginManager enforces 0700 permissions on user_dir."""
    manager = PluginManager(app=None)
    with tempfile.TemporaryDirectory() as td:
        user_path = Path(td) / "plugins"
        manager.user_dir = user_path

        # Create with insecure permissions
        user_path.mkdir()
        os.chmod(user_path, 0o777)

        manager._ensure_user_dir()

        st = os.stat(user_path)
        assert stat.S_IMODE(st.st_mode) == 0o700
