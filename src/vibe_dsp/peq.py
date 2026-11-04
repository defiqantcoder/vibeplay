"""Transducer-specific PEQ engine, anti-clipping gain staging, and EasyEffects integration."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from vibe_dsp.backup import create_backup

logger = logging.getLogger(__name__)

DEFAULT_EASYEFFECTS_OUTPUT_DIR = Path("~/.local/share/easyeffects/output").expanduser()
DEFAULT_PEQ_CACHE_DIR = Path("~/.config/vibe-dsp/peq/cache").expanduser()
DEFAULT_ACTIVE_PEQ_FILE = Path("~/.config/vibe-dsp/active_peq.json").expanduser()
BUNDLED_PROFILES_DIR = Path(__file__).parent / "profiles"


def _get_bundled_profiles_dir() -> Path:
    """Resolve bundled profiles directory, supporting PyInstaller frozen `_MEIPASS` archives."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass_dir = Path(getattr(sys, "_MEIPASS")) / "vibe_dsp" / "profiles"
        if meipass_dir.exists():
            return meipass_dir
    return BUNDLED_PROFILES_DIR


class FilterType(str, Enum):
    """Supported biquad filter topologies."""

    PEAK = "PK"
    LOW_SHELF = "LSQ"
    HIGH_SHELF = "HSQ"
    LOW_PASS = "LP"
    HIGH_PASS = "HP"
    NOTCH = "NOTCH"
    BAND_PASS = "BP"

    @classmethod
    def from_string(cls, value: str) -> FilterType:
        """Parse filter type from various standard nomenclature and abbreviations."""
        v = value.strip().upper().replace("-", "_").replace(" ", "_")
        if v in ("PK", "PEAK", "BELL", "PARAMETRIC"):
            return cls.PEAK
        if v in ("LS", "LSC", "LSQ", "LOW_SHELF", "LOWSHELF"):
            return cls.LOW_SHELF
        if v in ("HS", "HSC", "HSQ", "HIGH_SHELF", "HIGHSHELF"):
            return cls.HIGH_SHELF
        if v in ("LP", "LPC", "LOW_PASS", "LOWPASS"):
            return cls.LOW_PASS
        if v in ("HP", "HPC", "HIGH_PASS", "HIGHPASS"):
            return cls.HIGH_PASS
        if v in ("NO", "NOTCH"):
            return cls.NOTCH
        if v in ("BP", "BAND_PASS", "BANDPASS"):
            return cls.BAND_PASS
        return cls.PEAK

    def to_easyeffects_type(self) -> str:
        """Map to EasyEffects standard filter name."""
        mapping = {
            self.PEAK: "Bell",
            self.LOW_SHELF: "Low-shelf",
            self.HIGH_SHELF: "High-shelf",
            self.LOW_PASS: "Low-pass",
            self.HIGH_PASS: "High-pass",
            self.NOTCH: "Notch",
            self.BAND_PASS: "Band-pass",
        }
        return mapping.get(self, "Bell")


class BiquadFilter(BaseModel):
    """Specification of an individual parametric biquad equalizer filter."""

    filter_index: int = 1
    enabled: bool = True
    filter_type: FilterType = FilterType.PEAK
    frequency: float = Field(ge=10.0, le=48000.0, description="Center or cutoff frequency in Hz")
    gain: float = Field(default=0.0, ge=-48.0, le=48.0, description="Gain in decibels")
    q: float = Field(default=1.41, gt=0.01, le=50.0, description="Q-factor or resonance")
    slope: str = Field(default="x1", description="Filter slope (x1, x2, etc.)")


class PEQProfile(BaseModel):
    """Complete transducer parametric EQ profile with anti-clipping headroom."""

    name: str
    description: str = ""
    target_model: str | None = None
    source: str = ""
    explicit_preamp: float | None = None
    filters: list[BiquadFilter] = Field(default_factory=list)
    peak_positive_gain: float = Field(default=0.0, description="Evaluated peak boost in dB")
    calculated_preamp: float = Field(default=0.0, description="Anti-clipping negative preamp in dB")
    safety_margin_db: float = Field(default=0.3, description="Inter-sample clipping safety margin in dB")
    is_active: bool = False

    @property
    def active_filters(self) -> list[BiquadFilter]:
        """Return only enabled filter stages."""
        return [f for f in self.filters if f.enabled]


def biquad_frequency_response(
    filter_type: FilterType,
    f0: float,
    gain_db: float,
    q: float,
    freqs: np.ndarray,
    fs: float = 48000.0,
) -> np.ndarray:
    """Compute the complex frequency response magnitude in decibels for an RBJ biquad filter.

    Uses standard Robert Bristow-Johnson Audio EQ Cookbook discrete biquad equations.
    """
    if f0 <= 0.0 or fs <= 0.0 or len(freqs) == 0:
        return np.zeros_like(freqs, dtype=np.float64)

    w0 = 2.0 * np.pi * min(f0, fs * 0.499) / fs
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    safe_q = max(1e-4, q)
    alpha = sin_w0 / (2.0 * safe_q)
    a_amp = 10.0 ** (gain_db / 40.0)

    if filter_type == FilterType.PEAK:
        b0 = 1.0 + alpha * a_amp
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * a_amp
        a0 = 1.0 + alpha / a_amp
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / a_amp

    elif filter_type == FilterType.LOW_SHELF:
        sqrt_a = np.sqrt(a_amp)
        b0 = a_amp * ((a_amp + 1.0) - (a_amp - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha)
        b1 = 2.0 * a_amp * ((a_amp - 1.0) - (a_amp + 1.0) * cos_w0)
        b2 = a_amp * ((a_amp + 1.0) - (a_amp - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha)
        a0 = (a_amp + 1.0) + (a_amp - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha
        a1 = -2.0 * ((a_amp - 1.0) + (a_amp + 1.0) * cos_w0)
        a2 = (a_amp + 1.0) + (a_amp - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha

    elif filter_type == FilterType.HIGH_SHELF:
        sqrt_a = np.sqrt(a_amp)
        b0 = a_amp * ((a_amp + 1.0) + (a_amp - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha)
        b1 = -2.0 * a_amp * ((a_amp - 1.0) + (a_amp + 1.0) * cos_w0)
        b2 = a_amp * ((a_amp + 1.0) + (a_amp - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha)
        a0 = (a_amp + 1.0) - (a_amp - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha
        a1 = 2.0 * ((a_amp - 1.0) - (a_amp + 1.0) * cos_w0)
        a2 = (a_amp + 1.0) - (a_amp - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha

    elif filter_type == FilterType.LOW_PASS:
        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    elif filter_type == FilterType.HIGH_PASS:
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    elif filter_type == FilterType.NOTCH:
        b0 = 1.0
        b1 = -2.0 * cos_w0
        b2 = 1.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    elif filter_type == FilterType.BAND_PASS:
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha

    else:
        return np.zeros_like(freqs, dtype=np.float64)

    # Normalize by a0
    nb0 = b0 / a0
    nb1 = b1 / a0
    nb2 = b2 / a0
    na1 = a1 / a0
    na2 = a2 / a0

    # Evaluate H(e^jw) over freqs
    w = 2.0 * np.pi * freqs / fs
    z_inv = np.exp(-1j * w)
    z_inv2 = z_inv * z_inv

    num = nb0 + nb1 * z_inv + nb2 * z_inv2
    den = 1.0 + na1 * z_inv + na2 * z_inv2

    h = num / np.where(np.abs(den) < 1e-12, 1e-12, den)
    mag_db = 20.0 * np.log10(np.maximum(1e-12, np.abs(h)))
    return np.asarray(mag_db, dtype=np.float64)


def calculate_composite_curve(
    filters: list[BiquadFilter],
    freqs: np.ndarray | None = None,
    fs: float = 48000.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate continuous parametric frequency response curve across 20Hz-20kHz.

    Args:
        filters: Parametric EQ filter stages.
        freqs: Frequency grid array (defaults to 1000 points geometrically spaced from 20 to 20000 Hz).
        fs: Sampling rate in Hz.

    Returns:
        tuple[np.ndarray, np.ndarray]: (frequencies_array, composite_gain_db_array).
    """
    f_grid = freqs if freqs is not None else np.geomspace(20.0, 20000.0, 1000)
    total_gain = np.zeros_like(f_grid, dtype=np.float64)

    for flt in filters:
        if not flt.enabled:
            continue
        flt_db = biquad_frequency_response(
            filter_type=flt.filter_type,
            f0=flt.frequency,
            gain_db=flt.gain,
            q=flt.q,
            freqs=f_grid,
            fs=fs,
        )
        total_gain += flt_db

    return f_grid, total_gain


def calculate_anti_clipping_preamp(
    filters: list[BiquadFilter],
    safety_margin_db: float = 0.3,
    fs: float = 48000.0,
) -> tuple[float, float]:
    """Calculate the peak positive boost and corresponding negative digital preamp.

    Prevents inter-sample clipping (ISP) during 32-bit floating-point DSP processing
    by computing the composite peak gain and applying sufficient negative attenuation.

    Args:
        filters: Parametric EQ filter stages.
        safety_margin_db: Safety headroom in dB added to peak gain (default 0.3 dB).
        fs: Sampling rate for frequency curve evaluation.

    Returns:
        tuple[float, float]: (peak_positive_gain_db, recommended_preamp_db).
    """
    _, curve = calculate_composite_curve(filters=filters, fs=fs)
    raw_peak = float(np.max(curve)) if len(curve) > 0 else 0.0
    peak_positive_gain = max(0.0, raw_peak)

    if peak_positive_gain > 0.0:
        recommended_preamp = -round(peak_positive_gain + safety_margin_db, 2)
    else:
        recommended_preamp = 0.0

    return round(peak_positive_gain, 2), recommended_preamp


def apply_headroom_calculation(
    profile: PEQProfile,
    safety_margin_db: float = 0.3,
    fs: float = 48000.0,
) -> PEQProfile:
    """Evaluate profile filters and populate peak gain and anti-clipping preamp."""
    peak_gain, preamp = calculate_anti_clipping_preamp(
        filters=profile.filters,
        safety_margin_db=safety_margin_db,
        fs=fs,
    )
    profile.peak_positive_gain = peak_gain
    profile.safety_margin_db = safety_margin_db
    profile.calculated_preamp = preamp
    return profile


def parse_autoeq_text(text: str, name: str = "AutoEq Profile") -> PEQProfile:
    """Parse standard AutoEq or Squiglink parametric text format.

    Format example:
        Preamp: -6.8 dB
        Filter 1: ON PK Fc 28 Hz Gain 6.3 dB Q 0.54
        Filter 2: ON LSC Fc 105 Hz Gain 5.5 dB Q 0.71
        Filter 3: ON HSC Fc 10000 Hz Gain -2.0 dB Q 0.71
    """
    filters: list[BiquadFilter] = []
    explicit_preamp: float | None = None

    lines = text.strip().splitlines()
    filter_pattern = re.compile(
        r"Filter\s*(\d+)?:?\s*(ON|OFF)\s+([A-Za-z0-9_-]+)\s+Fc\s+([\d.]+)\s*Hz\s+Gain\s+([+-]?[\d.]+)\s*dB\s+Q\s+([\d.]+)",
        re.IGNORECASE,
    )
    preamp_pattern = re.compile(
        r"Preamp:?\s*([+-]?[\d.]+)\s*dB",
        re.IGNORECASE,
    )

    idx_counter = 1
    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("#"):
            continue

        p_match = preamp_pattern.search(line_clean)
        if p_match:
            try:
                explicit_preamp = float(p_match.group(1))
            except ValueError:
                pass
            continue

        f_match = filter_pattern.search(line_clean)
        if f_match:
            f_num = int(f_match.group(1)) if f_match.group(1) else idx_counter
            status = f_match.group(2).upper()
            f_type_str = f_match.group(3)
            fc = float(f_match.group(4))
            gain = float(f_match.group(5))
            q = float(f_match.group(6))

            filter_type = FilterType.from_string(f_type_str)
            enabled = status == "ON"

            filters.append(
                BiquadFilter(
                    filter_index=f_num,
                    enabled=enabled,
                    filter_type=filter_type,
                    frequency=fc,
                    gain=gain,
                    q=q,
                )
            )
            idx_counter += 1

    profile = PEQProfile(
        name=name,
        source="AutoEq / Squiglink Text",
        explicit_preamp=explicit_preamp,
        filters=filters,
    )
    return apply_headroom_calculation(profile)


def parse_json_filters(
    data: str | dict[str, Any] | list[Any],
    name: str = "Custom PEQ Profile",
) -> PEQProfile:
    """Parse user-defined JSON filter chains or EasyEffects preset JSON.

    Supports:
    - Object with 'filters' array and optional 'preamp' / 'name'.
    - Direct list of filter dicts.
    - EasyEffects output preset format containing 'equalizer#0'.
    """
    if isinstance(data, str):
        parsed = json.loads(data)
    else:
        parsed = data

    filters: list[BiquadFilter] = []
    explicit_preamp: float | None = None
    profile_name = name

    if isinstance(parsed, dict):
        if "name" in parsed and isinstance(parsed["name"], str):
            profile_name = parsed["name"]
        if "preamp" in parsed:
            try:
                explicit_preamp = float(parsed["preamp"])
            except (ValueError, TypeError):
                pass

        # Check for EasyEffects preset structure
        if "output" in parsed and "equalizer#0" in parsed["output"]:
            eq_block = parsed["output"]["equalizer#0"]
            if "input-gain" in eq_block:
                explicit_preamp = float(eq_block["input-gain"])
            left_bands = eq_block.get("left", {})
            for b_idx, (b_name, b_data) in enumerate(sorted(left_bands.items()), start=1):
                if not isinstance(b_data, dict):
                    continue
                filters.append(
                    BiquadFilter(
                        filter_index=b_idx,
                        enabled=not b_data.get("mute", False),
                        filter_type=FilterType.from_string(b_data.get("type", "Bell")),
                        frequency=float(b_data.get("frequency", 1000.0)),
                        gain=float(b_data.get("gain", 0.0)),
                        q=float(b_data.get("q", 1.41)),
                        slope=str(b_data.get("slope", "x1")),
                    )
                )
        elif "filters" in parsed and isinstance(parsed["filters"], list):
            for idx, item in enumerate(parsed["filters"], start=1):
                if not isinstance(item, dict):
                    continue
                filters.append(
                    BiquadFilter(
                        filter_index=item.get("filter_index", idx),
                        enabled=item.get("enabled", True),
                        filter_type=FilterType.from_string(item.get("type") or item.get("filter_type", "PK")),
                        frequency=float(item.get("frequency") or item.get("fc", 1000.0)),
                        gain=float(item.get("gain", 0.0)),
                        q=float(item.get("q", 1.41)),
                        slope=str(item.get("slope", "x1")),
                    )
                )

    elif isinstance(parsed, list):
        for idx, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                continue
            filters.append(
                BiquadFilter(
                    filter_index=item.get("filter_index", idx),
                    enabled=item.get("enabled", True),
                    filter_type=FilterType.from_string(item.get("type") or item.get("filter_type", "PK")),
                    frequency=float(item.get("frequency") or item.get("fc", 1000.0)),
                    gain=float(item.get("gain", 0.0)),
                    q=float(item.get("q", 1.41)),
                    slope=str(item.get("slope", "x1")),
                )
            )

    profile = PEQProfile(
        name=profile_name,
        source="JSON Filter Chain",
        explicit_preamp=explicit_preamp,
        filters=filters,
    )
    return apply_headroom_calculation(profile)


def ingest_peq_source(source: str | Path, name: str | None = None) -> PEQProfile:
    """Ingest PEQ configuration from a file path, raw JSON string, or AutoEq text."""
    path = Path(source).expanduser() if not str(source).startswith("{") and not str(source).startswith("[") else None

    if path and path.is_file():
        content = path.read_text(encoding="utf-8")
        prof_name = name or path.stem.replace("_", " ").title()
        if path.suffix.lower() == ".json":
            return parse_json_filters(content, name=prof_name)
        return parse_autoeq_text(content, name=prof_name)

    raw_str = str(source).strip()
    prof_name = name or "Custom PEQ"
    if raw_str.startswith("{") or raw_str.startswith("["):
        return parse_json_filters(raw_str, name=prof_name)
    return parse_autoeq_text(raw_str, name=prof_name)


def generate_easyeffects_preset(profile: PEQProfile) -> dict[str, Any]:
    """Build a complete EasyEffects output preset dictionary from a PEQ profile.

    Format matches EasyEffects modern PipeWire equalizer schema.
    """
    left_bands: dict[str, Any] = {}
    right_bands: dict[str, Any] = {}

    for idx, flt in enumerate(profile.filters):
        band_key = f"band{idx}"
        band_cfg = {
            "frequency": round(flt.frequency, 1),
            "gain": round(flt.gain, 2),
            "mode": "APO (DR)",
            "mute": not flt.enabled,
            "q": round(flt.q, 2),
            "slope": flt.slope,
            "solo": False,
            "type": flt.filter_type.to_easyeffects_type(),
            "width": round(flt.q, 2),
        }
        left_bands[band_key] = band_cfg
        right_bands[band_key] = dict(band_cfg)

    # EasyEffects output preset JSON structure
    return {
        "output": {
            "blocklist": [],
            "plugins_order": ["equalizer#0"],
            "equalizer#0": {
                "balance": 0.0,
                "bypass": False,
                "input-gain": profile.calculated_preamp,
                "output-gain": 0.0,
                "mode": "APO (DR)",
                "num-bands": len(profile.filters),
                "split-channels": False,
                "left": left_bands,
                "right": right_bands,
            },
        }
    }


def export_easyeffects_preset(
    profile: PEQProfile,
    target_dir: Path | None = None,
    filename: str | None = None,
    backup: bool = True,
) -> tuple[Path, Path | None]:
    """Export PEQ profile to an EasyEffects output preset JSON file.

    Generates an automated backup and rollback script before writing persistent changes.

    Args:
        profile: Tuned PEQ profile with anti-clipping preamp.
        target_dir: Destination directory (defaults to ~/.local/share/easyeffects/output).
        filename: Destination filename (defaults to '<safe_name>.json').
        backup: Whether to create automatic backup & rollback script (default True).

    Returns:
        tuple[Path, Path | None]: (preset_file_path, rollback_script_path).
    """
    out_dir = target_dir or DEFAULT_EASYEFFECTS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = filename or re.sub(r"[^\w\-_]", "_", profile.name.lower().strip())
    if not safe_name.endswith(".json"):
        safe_name = f"{safe_name}.json"

    preset_path = out_dir / safe_name
    rollback_script: Path | None = None

    if backup:
        _, rollback_script = create_backup(targets=[preset_path])

    preset_data = generate_easyeffects_preset(profile)
    preset_path.write_text(json.dumps(preset_data, indent=2), encoding="utf-8")
    logger.info("Exported EasyEffects preset to %s (preamp: %.2f dB)", preset_path, profile.calculated_preamp)

    return preset_path, rollback_script


def get_active_peq_state(state_file: Path | None = None) -> dict[str, Any]:
    """Retrieve current runtime PEQ active state."""
    sf = state_file or DEFAULT_ACTIVE_PEQ_FILE
    if sf.exists():
        try:
            return json.loads(sf.read_text(encoding="utf-8"))
        except Exception as err:
            logger.debug("Could not read active PEQ state: %s", err)
    return {
        "active_profile": None,
        "is_active": False,
        "preamp_db": 0.0,
        "filter_count": 0,
        "applied_at": None,
    }


def set_active_peq_state(state: dict[str, Any], state_file: Path | None = None) -> None:
    """Save runtime PEQ active state."""
    sf = state_file or DEFAULT_ACTIVE_PEQ_FILE
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(state, indent=2), encoding="utf-8")


def apply_peq_preset(
    preset_name_or_path: str | Path,
    toggle: bool = False,
    unload: bool = False,
    presets_dir: Path | None = None,
    easyeffects_bin: str = "easyeffects",
    state_file: Path | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Load or unload a PEQ preset dynamically via the EasyEffects CLI.

    Args:
        preset_name_or_path: Preset name (e.g. 'moondrop_blessing_2') or path.
        toggle: If True and target preset is already loaded, unload it; otherwise load it.
        unload: If True, unload/reset EasyEffects to bypass.
        presets_dir: Directory containing presets.
        easyeffects_bin: EasyEffects binary name or path.
        state_file: State persistence file.

    Returns:
        tuple[bool, str, dict[str, Any]]: (success, status_message, current_state).
    """
    ee_bin = shutil.which(easyeffects_bin)
    cur_state = get_active_peq_state(state_file=state_file)

    p_str = str(preset_name_or_path).strip()
    preset_name = Path(p_str).stem

    # Handle Unload or Toggle-off
    if unload or (toggle and cur_state.get("is_active") and cur_state.get("active_profile") == preset_name):
        if ee_bin:
            try:
                subprocess.run([ee_bin, "--reset"], capture_output=True, text=True, check=False)
            except Exception as err:
                logger.warning("Failed executing easyeffects --reset: %s", err)

        new_state = {
            "active_profile": None,
            "is_active": False,
            "preamp_db": 0.0,
            "filter_count": 0,
            "applied_at": None,
        }
        set_active_peq_state(new_state, state_file=state_file)
        msg = f"PEQ Profile '{preset_name}' successfully unloaded (Equalizer bypassed)."
        return True, msg, new_state

    # Load Preset
    ee_dir = presets_dir or DEFAULT_EASYEFFECTS_OUTPUT_DIR
    target_file = ee_dir / f"{preset_name}.json"

    preamp_val = 0.0
    f_count = 0
    if target_file.exists():
        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
            eq = data.get("output", {}).get("equalizer#0", {})
            preamp_val = float(eq.get("input-gain", 0.0))
            f_count = int(eq.get("num-bands", len(eq.get("left", {}))))
        except Exception:
            pass

    cmd_success = True
    notice = ""
    if ee_bin:
        try:
            res = subprocess.run(
                [ee_bin, "-l", preset_name],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
            if res.returncode != 0:
                cmd_success = False
                notice = f" (EasyEffects CLI returned code {res.returncode}: {res.stderr.strip()})"
        except Exception as err:
            cmd_success = False
            notice = f" (EasyEffects invocation error: {err})"
    else:
        notice = " (Notice: 'easyeffects' CLI binary not found in PATH; preset written and registered for daemon startup)"

    import datetime

    new_state = {
        "active_profile": preset_name,
        "is_active": True,
        "preamp_db": preamp_val,
        "filter_count": f_count,
        "applied_at": datetime.datetime.now().isoformat(),
    }
    set_active_peq_state(new_state, state_file=state_file)

    msg = f"PEQ Profile '{preset_name}' loaded with {preamp_val:.2f} dB anti-clipping preamp{notice}."
    return cmd_success, msg, new_state


def lookup_autoeq_model(
    model_name: str,
    cache_dir: Path | None = None,
    allow_network: bool = True,
) -> PEQProfile | None:
    """Lookup calibrated parametric EQ profile by headphone or IEM model name.

    Search sequence:
    1. Bundled reference profiles in vibe_dsp/profiles/.
    2. Local cache in ~/.config/vibe-dsp/peq/cache/.
    3. Remote jaakkopasanen/AutoEq GitHub index (if allow_network is True).
    """
    normalized_input = model_name.lower().replace("_", " ").replace("-", " ")
    clean_query = re.sub(r"[^\w\s]", " ", normalized_input).strip()
    tokens = [t for t in clean_query.split() if t]

    # 0. Check exported EasyEffects presets
    ee_dir = DEFAULT_EASYEFFECTS_OUTPUT_DIR
    if ee_dir.exists():
        exact_file = ee_dir / f"{model_name.strip()}.json"
        if exact_file.exists():
            try:
                return parse_json_filters(exact_file.read_text(encoding="utf-8"), name=exact_file.stem.replace("_", " ").title())
            except Exception:
                pass
        for f in ee_dir.glob("*.json"):
            stem_clean = f.stem.lower().replace("_", " ").replace("-", " ")
            if tokens and all(t in stem_clean for t in tokens):
                try:
                    return parse_json_filters(f.read_text(encoding="utf-8"), name=f.stem.replace("_", " ").title())
                except Exception:
                    pass

    # 1. Check bundled profiles
    bundled_dir = _get_bundled_profiles_dir()
    if bundled_dir.exists():
        for f in bundled_dir.glob("*.txt"):
            stem_clean = f.stem.lower().replace("_", " ").replace("-", " ")
            if tokens and all(t in stem_clean for t in tokens):
                content = f.read_text(encoding="utf-8")
                return parse_autoeq_text(content, name=f.stem.replace("_", " ").title())

    # 2. Check local cache directory
    c_dir = cache_dir or DEFAULT_PEQ_CACHE_DIR
    if c_dir.exists():
        for f in c_dir.glob("*.txt"):
            stem_clean = re.sub(r"[^\w\s]", "", f.stem.lower()).replace("_", " ")
            if all(t in stem_clean for t in tokens):
                content = f.read_text(encoding="utf-8")
                return parse_autoeq_text(content, name=f.stem.replace("_", " ").title())

    # 3. Optional remote GitHub fetch from AutoEq
    if allow_network:
        try:
            import httpx

            # Try common measurers (crinacle, oratory1990)
            formatted_name = model_name.strip()
            target_slugs = [
                f"crinacle/harman_in-ear_2019v2/{formatted_name}/{formatted_name} ParametricEQ.txt",
                f"oratory1990/harman_over-ear_2018/{formatted_name}/{formatted_name} ParametricEQ.txt",
            ]
            base_url = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"

            for slug in target_slugs:
                url = base_url + slug.replace(" ", "%20")
                resp = httpx.get(url, timeout=5.0)
                if resp.status_code == 200 and "Filter" in resp.text:
                    # Save to cache
                    c_dir.mkdir(parents=True, exist_ok=True)
                    safe_f = c_dir / f"{clean_query.replace(' ', '_')}.txt"
                    safe_f.write_text(resp.text, encoding="utf-8")
                    return parse_autoeq_text(resp.text, name=model_name)
        except Exception as err:
            logger.debug("AutoEq remote fetch unavailable: %s", err)

    return None


def list_available_presets(target_dir: Path | None = None) -> list[dict[str, Any]]:
    """List all available EasyEffects and bundled PEQ profiles with specs."""
    results: list[dict[str, Any]] = []
    ee_dir = target_dir or DEFAULT_EASYEFFECTS_OUTPUT_DIR
    active_state = get_active_peq_state()
    active_profile = active_state.get("active_profile")

    # Scanned EasyEffects presets
    if ee_dir.exists():
        for f in sorted(ee_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                eq = data.get("output", {}).get("equalizer#0", {})
                preamp = float(eq.get("input-gain", 0.0))
                num_bands = int(eq.get("num-bands", len(eq.get("left", {}))))
                results.append(
                    {
                        "name": f.stem,
                        "type": "EasyEffects Preset",
                        "path": str(f),
                        "preamp_db": preamp,
                        "bands": num_bands,
                        "is_active": active_profile == f.stem,
                    }
                )
            except Exception:
                continue

    # Bundled profiles
    bundled_dir = _get_bundled_profiles_dir()
    if bundled_dir.exists():
        for f in sorted(bundled_dir.glob("*.txt")):
            b_name = f.stem.replace("_", " ").title()
            if not any(r["name"] == f.stem for r in results):
                try:
                    prof = parse_autoeq_text(f.read_text(encoding="utf-8"), name=b_name)
                    results.append(
                        {
                            "name": f.stem,
                            "type": "Bundled AutoEq",
                            "path": str(f),
                            "preamp_db": prof.calculated_preamp,
                            "bands": len(prof.filters),
                            "is_active": active_profile == f.stem,
                        }
                    )
                except Exception:
                    continue

    return results
