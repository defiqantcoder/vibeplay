"""Unified desktop supervisor and entry point for vibeplay.

Provides a direct entry point module bridging to vibeplay.desktop.
"""

from __future__ import annotations

import sys

from vibeplay.desktop import (
    DEFAULT_BACKEND_HOST,
    DEFAULT_BACKEND_PORT,
    DesktopSupervisor,
    generate_audiophile_mpd_config,
    run_desktop,
)
from vibeplay.desktop.__main__ import main

__all__ = [
    "DEFAULT_BACKEND_HOST",
    "DEFAULT_BACKEND_PORT",
    "DesktopSupervisor",
    "generate_audiophile_mpd_config",
    "main",
    "run_desktop",
]

if __name__ == "__main__":
    sys.exit(main())
