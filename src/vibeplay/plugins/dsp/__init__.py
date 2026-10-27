from __future__ import annotations

import logging
from typing import Any

from vibeplay.plugins.base import VibePlugin

logger = logging.getLogger(__name__)


class DspPlugin(VibePlugin):
    def get_manifest(self) -> dict[str, Any]:
        return {
            "id": "dsp",
            "name": "DSP & Acoustics",
            "description": "Digital Signal Processing convolver and Parametric EQ tools",
            "author": "VibePlay Contributors",
            "version": "0.2.0",
            "icon": "🔧",
            "settings_schema": {},
        }

    def on_load(self, app: Any, config: dict[str, Any]) -> None:
        logger.info("DSP & Acoustics plugin initialized")

    def on_unload(self) -> None:
        logger.info("DSP & Acoustics plugin shut down")
