"""DSP & Spatial Audio Plugin for VibePlay.

Wraps Parametric Equalization (PEQ) and SOFA 7.1.4 HRTF Spatial Convolution.
CRITICAL AUDIOPHILE RULE: This entire processing chain is completely bypassed
when bit-perfect playback mode is active to preserve digital sample bit-perfection.
"""

from __future__ import annotations

import logging
from typing import Any

from vibeplay.plugins.base import Plugin, PluginMetadata

logger = logging.getLogger(__name__)


class DSPPlugin(Plugin):
    """Optional DSP add-on providing PEQ and SOFA spatial processing."""

    def __init__(self) -> None:
        super().__init__(
            metadata=PluginMetadata(
                name="dsp",
                version="0.1.0",
                description="Parametric EQ and SOFA 7.1.4 HRTF spatial convolution (bypassed in bit-perfect mode)",
                tags=["dsp", "peq", "spatial", "audiophile"],
            )
        )
        self.peq_enabled: bool = False
        self.spatial_enabled: bool = False
        self.active_peq_profile: str | None = None
        self.active_sofa_profile: str | None = None

    def initialize(self) -> None:
        """Initialize DSP subsystem."""
        self._is_initialized = True
        logger.info("DSP & Spatial Audio plugin initialized (ready for non-bit-perfect routing)")

    def shutdown(self) -> None:
        """Bypass and teardown all active DSP processing."""
        self.peq_enabled = False
        self.spatial_enabled = False
        self._is_initialized = False
        logger.info("DSP & Spatial Audio plugin shut down; all DSP bypassed")

    def should_bypass(self, bit_perfect_active: bool) -> bool:
        """Return True if DSP must be entirely bypassed (e.g. during bit-perfect playback)."""
        if bit_perfect_active:
            return True
        return not self.is_enabled

    def get_status(self) -> dict[str, Any]:
        """Return DSP telemetry and active status."""
        return {
            "enabled": self.is_enabled,
            "peq_enabled": self.peq_enabled,
            "spatial_enabled": self.spatial_enabled,
            "active_peq_profile": self.active_peq_profile,
            "active_sofa_profile": self.active_sofa_profile,
        }
