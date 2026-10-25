"""Validated desktop & hardware settings model with atomic JSON file persistence."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from vibeplay.ui.theme import THEME_PRESETS

logger = logging.getLogger(__name__)

DEFAULT_DESKTOP_SETTINGS_PATH = Path("~/.config/vibeplay/desktop_settings.json").expanduser()

VALID_ALSA_BUFFER_FRAMES = {32, 64, 128, 256, 512, 1024, 2048}
VALID_SAMPLE_RATE_LOCKS = {
    "auto",
    "44100",
    "48000",
    "88200",
    "96000",
    "176400",
    "192000",
    "384000",
}
VALID_DSP_PROFILES = {
    "pure-bitperfect",
    "spatial-headphones",
    "receiver-passthrough",
}
VALID_SPATIAL_MODES = {
    "stereo_direct",
    "3d_binaural",
    "spatial_binaural",
}
VALID_ANALYZER_BACKENDS = {"essentia", "librosa"}
VALID_CONTRAST_MODES = {"standard", "high-contrast"}
VALID_THEME_IDS = {preset.id for preset in THEME_PRESETS}

_ALSA_DEVICE_PATTERN = re.compile(r"^(?:(?:plug)?hw:\d+,\d+|default|pipewire)$")
_HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
_PEQ_PRESET_PATTERN = re.compile(r"^[a-z0-9_-]{2,64}$")


class DesktopSettings(BaseModel):
    """Comprehensive desktop, hardware transport, DSP, analyzer, and theme settings."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # 1. ALSA Hardware Transport
    alsa_device: str = Field(
        default="hw:0,0",
        description="ALSA hardware device identifier (e.g. hw:0,0, plughw:0,0, pipewire)",
    )
    alsa_exclusive_lock: bool = Field(
        default=True,
        description="Enforce exclusive hardware lock bypassing software mixers",
    )
    alsa_buffer_frames: int = Field(
        default=128,
        description="DMA ring buffer size in frames (power of two: 32..2048)",
    )
    alsa_period_count: int = Field(
        default=2,
        ge=2,
        le=8,
        description="Number of DMA periods per ring buffer (2..8)",
    )
    alsa_sample_rate_lock: str = Field(
        default="auto",
        description="Master clock sample rate lock ('auto' or specific Hz string)",
    )
    dpc_watchdog_enabled: bool = Field(
        default=True,
        description="Enable real-time kernel DPC latency and xrun watchdog telemetry",
    )

    # 2. DSP & Signal Chain
    dsp_profile: str = Field(
        default="pure-bitperfect",
        description="Active audio routing profile ('pure-bitperfect', 'spatial-headphones', 'receiver-passthrough')",
    )
    peq_profile: str = Field(
        default="none",
        description="Active Parametric EQ transducer profile preset name or 'none'",
    )
    peq_preamp_auto: bool = Field(
        default=True,
        description="Automatically calculate negative preamp headroom to prevent clipping",
    )
    peq_preamp_db: float = Field(
        default=-5.5,
        ge=-24.0,
        le=0.0,
        description="Negative preamp attenuation in dB (-24.0 to 0.0 dB)",
    )
    spatial_enabled: bool = Field(
        default=False,
        description="Enable 7.1.4 SOFA HRTF binaural virtualization",
    )
    spatial_mode: str = Field(
        default="stereo_direct",
        description="Spatial virtualization mode ('stereo_direct' or '3d_binaural')",
    )

    # 3. Essentia Feature Extraction
    analyzer_backend: str = Field(
        default="essentia",
        description="Primary audio feature extraction backend ('essentia' or 'librosa')",
    )
    analyzer_workers: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Parallel worker processes for audio feature extraction (1..32)",
    )
    analyzer_window_seconds: float = Field(
        default=60.0,
        ge=15.0,
        le=120.0,
        description="Duration in seconds of center audio window extracted for analysis (15..120)",
    )
    analyzer_fallback_enabled: bool = Field(
        default=True,
        description="Automatically fall back to Librosa multiprocessing if Essentia fails",
    )
    mood_confidence_threshold: float = Field(
        default=0.50,
        ge=0.05,
        le=0.95,
        description="Minimum classifier confidence threshold (0.05..0.95) for mood tag assignment",
    )

    # 4. Theme Engine
    theme_id: str = Field(
        default="god-of-ink",
        description="Active console palette preset ID",
    )
    custom_accent_color: str = Field(
        default="#6874a6",
        description="Custom primary/accent hex color override (#RRGGBB)",
    )
    contrast_mode: str = Field(
        default="standard",
        description="Display contrast mode ('standard' or 'high-contrast')",
    )

    @field_validator("alsa_device")
    @classmethod
    def validate_alsa_device(cls, v: str) -> str:
        cleaned = v.strip()
        if not _ALSA_DEVICE_PATTERN.match(cleaned):
            raise ValueError(f"Invalid ALSA device '{v}'. Expected 'hw:X,Y', 'plughw:X,Y', 'default', or 'pipewire'.")
        return cleaned

    @field_validator("alsa_buffer_frames")
    @classmethod
    def validate_buffer_frames(cls, v: int) -> int:
        if v not in VALID_ALSA_BUFFER_FRAMES:
            raise ValueError(f"Invalid buffer frame size {v}. Must be one of {sorted(VALID_ALSA_BUFFER_FRAMES)}.")
        return v

    @field_validator("alsa_sample_rate_lock")
    @classmethod
    def validate_sample_rate_lock(cls, v: str) -> str:
        cleaned = str(v).strip().lower()
        if cleaned not in VALID_SAMPLE_RATE_LOCKS:
            raise ValueError(f"Invalid sample rate lock '{v}'. Must be one of {sorted(VALID_SAMPLE_RATE_LOCKS)}.")
        return cleaned

    @field_validator("dsp_profile")
    @classmethod
    def validate_dsp_profile(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in VALID_DSP_PROFILES:
            raise ValueError(f"Invalid DSP profile '{v}'. Must be one of {sorted(VALID_DSP_PROFILES)}.")
        return cleaned

    @field_validator("peq_profile")
    @classmethod
    def validate_peq_profile(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned == "none":
            return cleaned
        if not _PEQ_PRESET_PATTERN.match(cleaned):
            raise ValueError(f"Invalid PEQ profile identifier '{v}'.")
        try:
            from vibe_dsp.peq import list_available_presets

            raw_presets = list_available_presets()
            available = {(p["name"].lower() if isinstance(p, dict) else str(p).lower()) for p in raw_presets} | {"none"}
            if len(available) > 1 and cleaned not in available:
                raise ValueError(f"Unknown PEQ preset '{v}'. Available presets: {sorted(available)}.")
        except ImportError:
            pass
        return cleaned

    @field_validator("spatial_mode")
    @classmethod
    def validate_spatial_mode(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in VALID_SPATIAL_MODES:
            raise ValueError(f"Invalid spatial mode '{v}'. Must be one of {sorted(VALID_SPATIAL_MODES)}.")
        return cleaned

    @field_validator("analyzer_backend")
    @classmethod
    def validate_analyzer_backend(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in VALID_ANALYZER_BACKENDS:
            raise ValueError(f"Invalid analyzer backend '{v}'. Must be one of {sorted(VALID_ANALYZER_BACKENDS)}.")
        return cleaned

    @field_validator("theme_id")
    @classmethod
    def validate_theme_id(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in VALID_THEME_IDS:
            raise ValueError(f"Invalid theme_id '{v}'. Must be one of {sorted(VALID_THEME_IDS)}.")
        return cleaned

    @field_validator("custom_accent_color")
    @classmethod
    def validate_custom_accent_color(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if not _HEX_COLOR_PATTERN.match(cleaned):
            raise ValueError(f"Invalid hex color '{v}'. Expected 6-digit hex format '#rrggbb'.")
        return cleaned

    @field_validator("contrast_mode")
    @classmethod
    def validate_contrast_mode(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if cleaned not in VALID_CONTRAST_MODES:
            raise ValueError(f"Invalid contrast_mode '{v}'. Must be one of {sorted(VALID_CONTRAST_MODES)}.")
        return cleaned


def load_desktop_settings(path: Path | None = None) -> DesktopSettings:
    """Load and validate desktop settings from JSON config file, returning defaults if missing."""
    target = (path or DEFAULT_DESKTOP_SETTINGS_PATH).expanduser()
    if not target.exists():
        return DesktopSettings()

    try:
        raw_text = target.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        if not isinstance(data, dict):
            logger.warning("Desktop settings file at %s is not a JSON object; using defaults.", target)
            return DesktopSettings()
        return DesktopSettings.model_validate(data)
    except Exception as err:
        logger.warning("Failed to load desktop settings from %s (%s); using defaults.", target, err)
        return DesktopSettings()


def save_desktop_settings(settings: DesktopSettings, path: Path | None = None) -> Path:
    """Atomically write validated desktop settings to disk with 0600 permissions."""
    target = (path or DEFAULT_DESKTOP_SETTINGS_PATH).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(settings.model_dump(mode="json"), indent=2, sort_keys=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=".desktop_settings_",
        suffix=".json.tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        os.chmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    return target


def update_desktop_settings(updates: dict[str, Any], path: Path | None = None) -> DesktopSettings:
    """Apply a partial or full dictionary of updates to persisted desktop settings, validate, and save."""
    current = load_desktop_settings(path)
    merged = current.model_dump()
    merged.update(updates)
    validated = DesktopSettings.model_validate(merged)
    save_desktop_settings(validated, path)
    return validated
