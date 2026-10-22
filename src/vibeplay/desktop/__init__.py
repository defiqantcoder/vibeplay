"""Desktop application shell, window management, and supervisor subsystem for vibeplay."""

from __future__ import annotations

from vibeplay.desktop.constants import (
    DEFAULT_BACKEND_HOST,
    DEFAULT_BACKEND_PORT,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_MIN_HEIGHT,
    DEFAULT_WINDOW_MIN_WIDTH,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_TITLE,
)
from vibeplay.desktop.environment import (
    DesktopEnvironment,
    find_free_loopback_port,
    generate_ephemeral_session_token,
    inspect_desktop_environment,
)
from vibeplay.desktop.settings import (
    DEFAULT_DESKTOP_SETTINGS_PATH,
    DesktopSettings,
    load_desktop_settings,
    save_desktop_settings,
    update_desktop_settings,
)
from vibeplay.desktop.supervisor import (
    DEFAULT_MPD_DATA_DIR,
    DesktopSupervisor,
    generate_audiophile_mpd_config,
    run_desktop,
)

__all__ = [
    "DEFAULT_BACKEND_HOST",
    "DEFAULT_BACKEND_PORT",
    "DEFAULT_DESKTOP_SETTINGS_PATH",
    "DEFAULT_MPD_DATA_DIR",
    "DEFAULT_WINDOW_HEIGHT",
    "DEFAULT_WINDOW_MIN_HEIGHT",
    "DEFAULT_WINDOW_MIN_WIDTH",
    "DEFAULT_WINDOW_WIDTH",
    "DesktopEnvironment",
    "DesktopSettings",
    "DesktopSupervisor",
    "WINDOW_TITLE",
    "find_free_loopback_port",
    "generate_audiophile_mpd_config",
    "generate_ephemeral_session_token",
    "inspect_desktop_environment",
    "load_desktop_settings",
    "run_desktop",
    "save_desktop_settings",
    "update_desktop_settings",
]
