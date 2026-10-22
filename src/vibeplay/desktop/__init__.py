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
from vibeplay.desktop.supervisor import (
    DEFAULT_MPD_DATA_DIR,
    DesktopSupervisor,
    generate_audiophile_mpd_config,
    run_desktop,
)

__all__ = [
    "DEFAULT_BACKEND_HOST",
    "DEFAULT_BACKEND_PORT",
    "DEFAULT_MPD_DATA_DIR",
    "DEFAULT_WINDOW_HEIGHT",
    "DEFAULT_WINDOW_MIN_HEIGHT",
    "DEFAULT_WINDOW_MIN_WIDTH",
    "DEFAULT_WINDOW_WIDTH",
    "DesktopEnvironment",
    "DesktopSupervisor",
    "WINDOW_TITLE",
    "find_free_loopback_port",
    "generate_audiophile_mpd_config",
    "generate_ephemeral_session_token",
    "inspect_desktop_environment",
    "run_desktop",
]
