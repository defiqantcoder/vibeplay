"""Data models for audio endpoints, hardware audit, and bit-perfect transport."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CardType(str, Enum):
    """Classification of detected ALSA audio card."""

    USB_DAC = "usb_dac"
    HDMI = "hdmi"
    SPEAKER_ANALOG = "speaker_analog"
    OTHER = "other"


class AudioEndpoint(BaseModel):
    """Specification of an audited audio hardware playback endpoint."""

    card_index: int = Field(description="ALSA card index (e.g. 0, 1)")
    device_index: int = Field(default=0, description="ALSA device index (e.g. 0, 3)")
    card_id: str = Field(description="ALSA card identifier string (e.g. 'KA15', 'sofhdadsp')")
    card_name: str = Field(description="Hardware model name (e.g. 'FIIO KA15')")
    driver: str = Field(description="ALSA driver module (e.g. 'USB-Audio', 'sof-hda-dsp')")
    device_name: str = Field(description="PCM device name (e.g. 'USB Audio', 'HDA Analog (*)')")
    card_type: CardType = Field(description="Category of the audio endpoint")
    usb_id: str | None = Field(default=None, description="USB vendor:product ID (e.g. '2972:0104')")
    usb_bus: str | None = Field(default=None, description="USB bus address (e.g. '003/014')")
    rates: list[int] = Field(default_factory=list, description="Supported native sampling rates in Hz")
    formats: list[str] = Field(default_factory=list, description="Supported PCM formats (e.g. S32_LE, DSD)")
    bit_depths: list[int] = Field(default_factory=list, description="Supported bit depths (e.g. 16, 24, 32)")
    channels: int = Field(default=2, description="Channel count")
    is_connected: bool = Field(default=True, description="Whether endpoint is actively detected")
    priority_score: int = Field(default=0, description="Routing priority (higher is preferred)")
    pipewire_node_name: str | None = Field(default=None, description="PipeWire ALSA node name")

    @property
    def hw_device(self) -> str:
        """Direct ALSA hardware address."""
        return f"hw:{self.card_index},{self.device_index}"

    @property
    def plughw_device(self) -> str:
        """Transparent software conversion ALSA plug address."""
        return f"plughw:{self.card_index},{self.device_index}"

    @property
    def max_rate(self) -> int:
        """Highest supported sample rate."""
        return max(self.rates) if self.rates else 48000

    @property
    def max_bit_depth(self) -> int:
        """Highest supported bit depth."""
        return max(self.bit_depths) if self.bit_depths else 16


class AuditReport(BaseModel):
    """Complete summary of audio hardware audit."""

    endpoints: list[AudioEndpoint] = Field(default_factory=list, description="All detected audio endpoints")
    active_dac: AudioEndpoint | None = Field(default=None, description="Prioritized connected external DAC")
    fallback_endpoint: AudioEndpoint | None = Field(default=None, description="Fallback speaker or internal card")
    unlocked_rates: list[int] = Field(
        default_factory=lambda: [44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000],
        description="Master list of rates to unlock in PipeWire",
    )
