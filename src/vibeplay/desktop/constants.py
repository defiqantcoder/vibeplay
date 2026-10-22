"""Constants and runtime defaults for the vibeplay desktop application shell."""

from __future__ import annotations

# Window Geometry and Appearance
WINDOW_TITLE = "vibeplay — Audiophile Precision Console"
DEFAULT_WINDOW_WIDTH = 1380
DEFAULT_WINDOW_HEIGHT = 860
DEFAULT_WINDOW_MIN_WIDTH = 1024
DEFAULT_WINDOW_MIN_HEIGHT = 680

# Localhost Backend Networking & Security
DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000
MAX_PORT_SEARCH_ATTEMPTS = 50
SESSION_TOKEN_HEADER = "X-Vibeplay-Session"
SESSION_COOKIE_NAME = "vibeplay_session_token"

# Target OS and Windowing Stack
SUPPORTED_OS_NAME = "Ubuntu 24.04 LTS"
TARGET_GUI_BACKEND = "gtk3-webkit2"

# FreeDesktop Application Metadata
APP_ID = "com.vibeplay.player"
APP_NAME = "vibeplay"
APP_CATEGORY = "AudioVideo;Audio;Player;"
DESKTOP_ENTRY_FILENAME = "vibeplay.desktop"
SYSTEMD_SERVICE_NAME = "vibeplay.service"
