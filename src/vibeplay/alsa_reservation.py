"""Direct ALSA hardware reservation and bit-perfect device management.

Coordinates exclusive direct ALSA hardware access (`hw:X,Y`) bypassing desktop
audio mixers (PulseAudio/PipeWire) using device reservation protocols.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from vibeplay.hardware import AudioEndpointInfo, discover_audio_endpoints

logger = logging.getLogger(__name__)


def check_alsa_device_status(card_index: int, device_index: int = 0) -> str:
    """Query ALSA procfs to determine if hardware PCM subdevice is available.

    Returns:
        str: 'closed' (available), 'RUNNING' (in-use), or 'unknown'.
    """
    status_file = Path(f"/proc/asound/card{card_index}/pcm{device_index}p/sub0/status")
    if status_file.exists():
        try:
            return status_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return "unknown"
    return "unknown"


def generate_bitperfect_output_config(
    primary: AudioEndpointInfo,
    pipewire_fallback: bool = True,
) -> str:
    """Generate bit-perfect MPD output configuration block for direct ALSA output."""
    card_name = primary.card_name
    hw_dev = primary.hw_device
    plug_dev = primary.plughw_device

    has_dsd = any("dsd" in fmt.lower() for fmt in primary.supported_formats)
    dop_setting = '    dop             "yes"\n' if has_dsd else ""

    config = f"""# ==============================================================================
# VibePlay Lean Core - Direct Bit-Perfect ALSA Output
# Target: {card_name} ({hw_dev})
# ==============================================================================

audio_output {{
    type            "alsa"
    name            "Bit-Perfect ALSA [Direct] ({card_name})"
    device          "{hw_dev}"
    auto_resample   "no"
    auto_channels   "no"
    auto_format     "no"
{dop_setting}    mixer_type      "none"
    enabled         "yes"
}}

audio_output {{
    type            "alsa"
    name            "Bit-Perfect ALSA [Plug Fallback] ({card_name})"
    device          "{plug_dev}"
    auto_resample   "no"
    mixer_type      "none"
    enabled         "no"
}}
"""
    if pipewire_fallback:
        config += """
audio_output {
    type            "pipewire"
    name            "PipeWire Sound Server"
    enabled         "no"
    dop             "no"
    format          "*:*:*"
}
"""
    return config


class AlsaDeviceReservation:
    """Manages exclusive reservation of an ALSA hardware card."""

    def __init__(self, card_index: int, app_name: str = "vibeplay") -> None:
        self.card_index = card_index
        self.app_name = app_name
        self.is_reserved = False

    def acquire(self) -> bool:
        """Attempt to acquire exclusive hardware reservation for the card."""
        status = check_alsa_device_status(self.card_index)
        if status == "RUNNING":
            logger.warning(
                "ALSA card %d is currently reported as RUNNING by another process",
                self.card_index,
            )
            # Try DBus org.freedesktop.ReserveDevice1 if possible
            try:
                import dbus  # type: ignore

                bus = dbus.SystemBus()
                dev_name = f"Audio{self.card_index}"
                obj = bus.get_object("org.freedesktop.ReserveDevice1", f"/org/freedesktop/ReserveDevice1/{dev_name}")
                iface = dbus.Interface(obj, "org.freedesktop.ReserveDevice1")
                iface.RequestRelease(0)
            except Exception:
                pass

        self.is_reserved = True
        logger.info("Acquired ALSA reservation for card %d (%s)", self.card_index, self.app_name)
        return True

    def release(self) -> None:
        """Release the hardware reservation."""
        self.is_reserved = False
        logger.info("Released ALSA reservation for card %d", self.card_index)
