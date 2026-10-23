"""Data models for audio endpoints, hardware audit, and bit-perfect transport."""

from __future__ import annotations

from enum import Enum

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
        default_factory=lambda: [
            44100,
            48000,
            88200,
            96000,
            176400,
            192000,
            352800,
            384000,
        ],
        description="Master list of rates to unlock in PipeWire",
    )


class LatencyHealthRating(str, Enum):
    """Concise real-time audio thread latency health classification."""

    GOOD = "Good"
    MARGINAL = "Marginal"
    THROTTLED = "Throttled"


class CpuCorePowerState(BaseModel):
    """Hardware power and frequency scaling state of a CPU core."""

    core_id: int
    governor: str = "unknown"
    cur_freq_mhz: float = 0.0
    max_freq_mhz: float = 0.0
    epp: str | None = None
    is_throttled: bool = False


class PowerProfileReport(BaseModel):
    """ACPI CPU throttling and frequency scaling audit."""

    ac_online: bool = True
    battery_present: bool = False
    battery_status: str | None = None
    cores: list[CpuCorePowerState] = Field(default_factory=list)
    is_throttled: bool = False
    active_governor: str = "unknown"
    recommendation: str = ""


class XrunReport(BaseModel):
    """Buffer underruns and ALSA/PipeWire PCM hardware status."""

    card_index: int = 1
    device_index: int = 0
    state: str = "closed"
    xrun_count: int = 0
    active_rate: int | None = None
    buffer_size: int | None = None
    period_size: int | None = None
    pipewire_errors: int = 0
    pipewire_rate: int | None = None


class JitterMetrics(BaseModel):
    """Real-time audio thread scheduling jitter measurements in microseconds."""

    min_jitter_us: float = 0.0
    avg_jitter_us: float = 0.0
    max_jitter_us: float = 0.0
    stddev_jitter_us: float = 0.0
    sample_count: int = 0
    source: str = "python_perf_counter"


class MicroStutterAnomaly(BaseModel):
    """Logged micro-stutter latency spike anomaly."""

    timestamp: str
    jitter_us: float
    xrun_detected: bool = False
    active_rate: int | None = None
    system_load: float = 0.0
    cpu_throttled: bool = False
    message: str = ""


class LatencyMonitorReport(BaseModel):
    """Master latency watchdog report with DPC jitter, xruns, and power state."""

    timestamp: str
    health_rating: LatencyHealthRating
    xrun_report: XrunReport
    jitter_metrics: JitterMetrics
    power_profile: PowerProfileReport
    rtkit_granted: bool = False
    rtkit_details: str = ""
    system_load: float = 0.0
    anomalies: list[MicroStutterAnomaly] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
