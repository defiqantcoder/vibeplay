#!/usr/bin/env python3
"""Export complete VibePlay algorithmic specification to assets/vibe_spec.json.

Inspects the desktop audio engine, DSP pipeline, feature vector formulating logic,
harmonic mixing rules, vibe presets, derived mood definitions, and energy arc curves,
validating the output against a strict schema.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Ensure execution inside project virtualenv if running from system python
try:
    import pydantic  # noqa: F401
except ImportError:
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists() and sys.executable != str(venv_python):
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)
    raise

import json
import math
from typing import Any

from pydantic import BaseModel, Field, field_validator

from vibe_dsp.peq import BiquadFilter, FilterType, PEQProfile
from vibeplay.config import Settings
from vibeplay.playlist import (
    CAMELOT_MAJOR,
    CAMELOT_MINOR,
    MOOD_KEYS,
    VIBE_PRESETS,
    camelot_distance,
)

# =========================================================================
# Schema Definitions
# =========================================================================


class AlgorithmWeightsSpec(BaseModel):
    """Specification of feature weighting and dimensionality reduction."""

    bpm_harmonic_weight: float = Field(..., ge=0.0, le=1.0)
    relative_weight_vs_absolute_weight: dict[str, float] = Field(...)
    column_weights: dict[str, float] = Field(...)
    heuristic_mood_keys: list[str] = Field(..., min_length=7, max_length=7)
    embedding_dimension: int = Field(..., ge=16, le=128)
    pca_embedding_dimensions: int = Field(..., ge=1, le=64)


class VibePresetConstraint(BaseModel):
    """Bounds and constraints defining a single vibe preset."""

    energy_min: float | None = Field(default=None, ge=0.0, le=1.0)
    energy_max: float | None = Field(default=None, ge=0.0, le=1.0)
    danceability_min: float | None = Field(default=None, ge=0.0, le=1.0)
    danceability_max: float | None = Field(default=None, ge=0.0, le=1.0)
    bpm_min: float | None = Field(default=None, ge=0.0, le=300.0)
    bpm_max: float | None = Field(default=None, ge=0.0, le=300.0)
    mood_min: dict[str, float] = Field(default_factory=dict)


class DerivedMoodSpec(BaseModel):
    """Formula and coefficients used to derive complex mood metrics."""

    name: str
    description: str
    source_features: list[str]
    coefficients: dict[str, float]
    formula: str


class CamelotSpec(BaseModel):
    """Harmonic mixing specifications, key mappings, and transition tables."""

    major_keys: dict[str, str]
    minor_keys: dict[str, str]
    transition_scores: dict[str, float]
    distance_matrix: dict[str, dict[str, int]]


class EnergyArcCurveSpec(BaseModel):
    """Mathematical trajectory sampled at normalized playlist positions."""

    id: str
    name: str
    formula: str
    description: str
    normalized_positions: list[float]
    sampled_energy: list[float]
    min_energy: float
    max_energy: float

    @field_validator("sampled_energy")
    @classmethod
    def validate_samples(cls, v: list[float]) -> list[float]:
        if len(v) != 11:
            raise ValueError(f"Energy arc curve must contain exactly 11 sample points, got {len(v)}")
        for x in v:
            if not (0.0 <= x <= 1.0):
                raise ValueError(f"Energy sample {x} out of bounds [0.0, 1.0]")
        return v


class BiquadFilterRangesSpec(BaseModel):
    """Safety and validation bounds for parametric EQ biquad stages."""

    frequency_hz: dict[str, float | str]
    gain_db: dict[str, float | str]
    q_factor: dict[str, float | str]
    headroom_margin_db: float
    supported_topologies: list[str]


class BiquadStageCoefficients(BaseModel):
    """Second-order IIR biquad section numerator and denominator coefficients."""

    stage_name: str
    topology: str
    b0: float
    b1: float
    b2: float
    a0: float = 1.0
    a1: float
    a2: float


class SampleRateKWeightingSpec(BaseModel):
    """Two-stage K-weighting filter cascade for a specific sampling frequency."""

    sample_rate_hz: int
    stage1_high_shelf: BiquadStageCoefficients
    stage2_high_pass: BiquadStageCoefficients


class KWeightingLoudnessSpec(BaseModel):
    """ITU-R BS.1770-4 K-weighting filter parameters across standard audio sample rates."""

    standard: str = "ITU-R BS.1770-4 / EBU R128"
    description: str
    coefficients: dict[str, SampleRateKWeightingSpec]


class VibeSpec(BaseModel):
    """Complete serialized VibePlay algorithm specification."""

    schema_version: str = "1.0.0"
    specification_title: str = "VibePlay Desktop Audio Engine & Algorithmic Specification"
    algorithm_weights: AlgorithmWeightsSpec
    vibe_presets: dict[str, VibePresetConstraint]
    derived_moods: dict[str, DerivedMoodSpec]
    camelot_harmonic_system: CamelotSpec
    energy_arcs: dict[str, EnergyArcCurveSpec]
    biquad_filter_validation: BiquadFilterRangesSpec
    k_weighting_loudness: KWeightingLoudnessSpec


# =========================================================================
# Introspection & Construction Functions
# =========================================================================


def extract_algorithm_weights() -> AlgorithmWeightsSpec:
    """Introspect active settings for feature formulation and dimensionality weights."""
    cfg = Settings()
    w_bpm = float(cfg.weight_bpm)
    h_ratio = float(cfg.bpm_harmonic_weight)

    # Relative weight vs absolute weight
    circular_harmonic_weight = round(w_bpm * math.sqrt(h_ratio / 2.0), 6)
    absolute_bpm_weight = round(w_bpm * math.sqrt(1.0 - h_ratio), 6)

    return AlgorithmWeightsSpec(
        bpm_harmonic_weight=h_ratio,
        relative_weight_vs_absolute_weight={
            "circular_harmonic_bpm": circular_harmonic_weight,
            "standardized_absolute_bpm": absolute_bpm_weight,
        },
        column_weights={
            "bpm": float(cfg.weight_bpm),
            "loudness": float(cfg.weight_loudness),
            "danceability": float(cfg.weight_danceability),
            "energy": float(cfg.weight_energy),
            "mood": float(cfg.weight_mood),
            "embedding": float(cfg.weight_embedding),
        },
        heuristic_mood_keys=list(MOOD_KEYS),
        embedding_dimension=64,
        pca_embedding_dimensions=int(cfg.pca_embedding_dimensions),
    )


def extract_vibe_presets() -> dict[str, VibePresetConstraint]:
    """Extract and validate all vibe preset constraints from the playlist engine."""
    presets_spec: dict[str, VibePresetConstraint] = {}
    for name, config in VIBE_PRESETS.items():
        presets_spec[name] = VibePresetConstraint(
            energy_min=config.get("energy_min"),
            energy_max=config.get("energy_max"),
            danceability_min=config.get("danceability_min"),
            danceability_max=config.get("danceability_max"),
            bpm_min=config.get("bpm_min"),
            bpm_max=config.get("bpm_max"),
            mood_min=config.get("mood_min", {}),
        )

    if len(presets_spec) < 20:
        raise ValueError(f"Expected at least 20 vibe presets, found {len(presets_spec)}")

    return presets_spec


def extract_derived_moods() -> dict[str, DerivedMoodSpec]:
    """Define the 8 derived mood composite formulas and linear coefficients."""
    derived_specs: dict[str, DerivedMoodSpec] = {
        "chill": DerivedMoodSpec(
            name="Chill / Relaxed",
            description="Low energy combined with high relaxed probability and low acoustic harshness.",
            source_features=["relaxed", "energy", "loudness"],
            coefficients={"relaxed": 0.50, "inverse_energy": 0.35, "inverse_loudness": 0.15},
            formula="0.50 * relaxed + 0.35 * (1.0 - energy) + 0.15 * (1.0 - norm_loud)",
        ),
        "energetic": DerivedMoodSpec(
            name="Energetic / High Tempo",
            description="High energetic impulse driven by peak energy, party mood, and elevated tempo.",
            source_features=["energy", "party", "bpm"],
            coefficients={"energy": 0.50, "party": 0.30, "norm_bpm": 0.20},
            formula="0.50 * energy + 0.30 * party + 0.20 * norm_bpm",
        ),
        "workout": DerivedMoodSpec(
            name="Workout / Driving Pulse",
            description="Maximal energy and steady rhythmic cadence designed for athletic focus.",
            source_features=["energy", "danceability", "bpm"],
            coefficients={"energy": 0.55, "danceability": 0.25, "norm_bpm": 0.20},
            formula="0.55 * energy + 0.25 * danceability + 0.20 * norm_bpm",
        ),
        "melancholic": DerivedMoodSpec(
            name="Melancholic / Reflective",
            description="Deep introspective emotion dominated by minor tonality and low kinetic energy.",
            source_features=["sad", "inverse_major", "inverse_energy"],
            coefficients={"sad": 0.50, "inverse_major": 0.30, "inverse_energy": 0.20},
            formula="0.50 * sad + 0.30 * (1.0 - is_major) + 0.20 * (1.0 - energy)",
        ),
        "euphoric": DerivedMoodSpec(
            name="Euphoric / Peak Joy",
            description="Unrestrained happiness and celebratory energy with high dance groove.",
            source_features=["happy", "party", "danceability"],
            coefficients={"happy": 0.45, "party": 0.35, "danceability": 0.20},
            formula="0.45 * happy + 0.35 * party + 0.20 * danceability",
        ),
        "deep_focus": DerivedMoodSpec(
            name="Deep Focus / Study",
            description="Subtle acoustic warmth with constrained dynamics and zero jarring transients.",
            source_features=["relaxed", "acoustic", "inverse_energy"],
            coefficients={"relaxed": 0.50, "acoustic": 0.30, "inverse_energy": 0.20},
            formula="0.50 * relaxed + 0.30 * acoustic + 0.20 * (1.0 - energy)",
        ),
        "dark_intense": DerivedMoodSpec(
            name="Dark & Intense",
            description="Menacing, aggressive sonic character with industrial electronic weight.",
            source_features=["aggressive", "electronic", "energy"],
            coefficients={"aggressive": 0.45, "energy": 0.30, "electronic": 0.25},
            formula="0.45 * aggressive + 0.30 * energy + 0.25 * electronic",
        ),
        "ambient": DerivedMoodSpec(
            name="Ambient / Atmospheric",
            description="Expansive soundscapes characterized by minimal percussion and organic textures.",
            source_features=["acoustic", "relaxed", "inverse_danceability"],
            coefficients={"acoustic": 0.45, "relaxed": 0.35, "inverse_danceability": 0.20},
            formula="0.45 * acoustic + 0.35 * relaxed + 0.20 * (1.0 - danceability)",
        ),
    }

    if len(derived_specs) != 8:
        raise ValueError(f"Expected exactly 8 derived mood specs, found {len(derived_specs)}")

    return derived_specs


def extract_camelot_system() -> CamelotSpec:
    """Build the complete Camelot key wheel, distance matrix, and score tables."""
    all_keys = [f"{i}A" for i in range(1, 13)] + [f"{i}B" for i in range(1, 13)]

    # 24x24 distance matrix
    dist_mat: dict[str, dict[str, int]] = {}
    for k1 in all_keys:
        dist_mat[k1] = {}
        for k2 in all_keys:
            dist_mat[k1][k2] = camelot_distance(k1, k2)

    # Transition score table
    transition_scores = {
        "exact_key_match_dist_0": 1.0,
        "harmonic_consonant_or_relative_dist_1": 0.95,
        "energy_whole_step_dist_2": 0.70,
        "moderate_leap_dist_3": 0.50,
        "dissonant_clash_dist_4_plus": 0.20,
    }

    return CamelotSpec(
        major_keys=dict(CAMELOT_MAJOR),
        minor_keys=dict(CAMELOT_MINOR),
        transition_scores=transition_scores,
        distance_matrix=dist_mat,
    )


def extract_energy_arcs() -> dict[str, EnergyArcCurveSpec]:
    """Calculate and sample 20 energy arc curves at 11 normalized positions."""
    normalized_positions = [round(i / 10.0, 1) for i in range(11)]

    # 20 distinct mathematical trajectories
    arc_definitions: list[dict[str, Any]] = [
        {
            "id": "energy_ramp",
            "name": "Energy Ramp",
            "formula": "0.25 + 0.65 * t",
            "desc": "Linear upward progression building from calm opening to peak finale.",
            "fn": lambda t: 0.25 + 0.65 * t,
        },
        {
            "id": "cooldown",
            "name": "Cooldown",
            "formula": "0.85 - 0.60 * t",
            "desc": "Linear descending trajectory easing down from high energy into stillness.",
            "fn": lambda t: 0.85 - 0.60 * t,
        },
        {
            "id": "peak_hour_wave",
            "name": "Peak-Hour Wave",
            "formula": "0.35 + 0.55 * sin(pi * t)",
            "desc": "Classic bell curve rising to an intense mid-set climax before gentle decay.",
            "fn": lambda t: 0.35 + 0.55 * math.sin(math.pi * t),
        },
        {
            "id": "double_peak",
            "name": "Double Peak",
            "formula": "0.40 + 0.45 * (sin(2*pi*t) ** 2)",
            "desc": "Twin apex journey featuring two euphoric climaxes separated by an atmospheric breather.",
            "fn": lambda t: min(1.0, max(0.20, 0.40 + 0.45 * (math.sin(2.0 * math.pi * t) ** 2))),
        },
        {
            "id": "sunrise_roller",
            "name": "Sunrise Roller",
            "formula": "0.30 + 0.50 * t + 0.15 * sin(4*pi*t)",
            "desc": "Ascending cyclic wave with rhythmic rollers culminating in morning dawn brilliance.",
            "fn": lambda t: min(1.0, max(0.20, 0.30 + 0.50 * t + 0.15 * math.sin(4.0 * math.pi * t))),
        },
        {
            "id": "deep_dive",
            "name": "Deep Dive",
            "formula": "0.80 - 0.55 * sin(pi * t)",
            "desc": "Inverted valley plunging from bright energy into sub-bass abyssal depths before rising.",
            "fn": lambda t: min(1.0, max(0.15, 0.80 - 0.55 * math.sin(math.pi * t))),
        },
        {
            "id": "heartbeat_wave",
            "name": "Heartbeat Wave",
            "formula": "0.60 + 0.25 * sin(3*pi*t)",
            "desc": "Pulsing rhythmic oscillations simulating natural cardiac cycles of tension and release.",
            "fn": lambda t: min(1.0, max(0.20, 0.60 + 0.25 * math.sin(3.0 * math.pi * t))),
        },
        {
            "id": "slow_burn",
            "name": "Slow Burn",
            "formula": "0.25 + 0.65 * (t ** 3)",
            "desc": "Extended subtle incubation exploding into exponential explosive energy in the final third.",
            "fn": lambda t: min(1.0, max(0.20, 0.25 + 0.65 * (t ** 3))),
        },
        {
            "id": "steady_pulse",
            "name": "Steady Pulse",
            "formula": "0.60",
            "desc": "Uniform plateau delivering consistent, locked-in groove suitable for work or endurance.",
            "fn": lambda t: 0.60,
        },
        {
            "id": "late_night_chill",
            "name": "Late Night Chill",
            "formula": "max(0.20, 0.45 - 0.25 * t)",
            "desc": "Gentle nocturnal taper drifting effortlessly into midnight introspection.",
            "fn": lambda t: max(0.20, 0.45 - 0.25 * t),
        },
        {
            "id": "stairway_to_heaven",
            "name": "Stairway Steps",
            "formula": "0.25 + 0.18 * floor(t * 4)",
            "desc": "Discrete stepped tiers holding energy steady at each plateau before stepping upward.",
            "fn": lambda t: min(1.0, 0.25 + 0.18 * math.floor(min(t, 0.999) * 4)),
        },
        {
            "id": "rollercoaster",
            "name": "Rollercoaster",
            "formula": "0.55 + 0.35 * sin(5*pi*t)",
            "desc": "Rapid undulating peaks and dips creating a high-velocity sensation of movement.",
            "fn": lambda t: min(1.0, max(0.20, 0.55 + 0.35 * math.sin(5.0 * math.pi * t))),
        },
        {
            "id": "valley_canyon",
            "name": "Valley Canyon",
            "formula": "0.85 - 0.65 * sin(pi * t)",
            "desc": "High-octane intro and outro hugging an ultra-low ambient canyon in the mid-session.",
            "fn": lambda t: min(1.0, max(0.15, 0.85 - 0.65 * math.sin(math.pi * t))),
        },
        {
            "id": "exponential_drop",
            "name": "Exponential Drop",
            "formula": "0.90 - 0.70 * (t ** 2)",
            "desc": "High-impact opening that drops with accelerating deceleration into ambient quietude.",
            "fn": lambda t: max(0.20, 0.90 - 0.70 * (t ** 2)),
        },
        {
            "id": "sine_plateau",
            "name": "Sine Plateau",
            "formula": "0.30 + 0.60 * sin(pi * t / 2.0)",
            "desc": "Rapid climb during the first quarter transitioning to a sustained high-energy plateau.",
            "fn": lambda t: min(1.0, 0.30 + 0.60 * math.sin(math.pi * t / 2.0)),
        },
        {
            "id": "early_apex",
            "name": "Early Apex",
            "formula": "0.35 + 0.60 * sin(pi * (t ** 0.5))",
            "desc": "Quick surge to an early climax followed by a long, graceful wind-down.",
            "fn": lambda t: min(1.0, max(0.20, 0.35 + 0.60 * math.sin(math.pi * (t ** 0.5)))),
        },
        {
            "id": "late_apex",
            "name": "Late Apex",
            "formula": "0.25 + 0.70 * (sin(pi * (t ** 2)) ** 0.5)",
            "desc": "Patient slow-burn build peaking at the 85% mark before a brief outro cooldown.",
            "fn": lambda t: min(1.0, max(0.20, 0.25 + 0.70 * (math.sin(math.pi * (t ** 2)) ** 0.5) if math.sin(math.pi * (t ** 2)) >= 0 else 0.25)),
        },
        {
            "id": "ambient_drift",
            "name": "Ambient Drift",
            "formula": "0.25 + 0.12 * sin(2*pi*t)",
            "desc": "Minimalist, undulating low-energy flow designed for sleep, meditation, or reading.",
            "fn": lambda t: round(0.25 + 0.12 * math.sin(2.0 * math.pi * t), 4),
        },
        {
            "id": "sawtooth_build",
            "name": "Sawtooth Build",
            "formula": "0.30 + 0.25 * ((t * 3) % 1) + 0.40 * t",
            "desc": "Three sequential ramp cycles, each starting higher than the previous build.",
            "fn": lambda t: min(1.0, max(0.20, 0.30 + 0.25 * ((t * 3.0) % 1.0) + 0.40 * t)),
        },
        {
            "id": "volcano_eruption",
            "name": "Volcano Eruption",
            "formula": "0.20 + 0.75 / (1.0 + exp(-12.0 * (t - 0.60)))",
            "desc": "Subdued subterranean rumble suddenly erupting into explosive seismic energy.",
            "fn": lambda t: min(1.0, max(0.20, 0.20 + 0.75 / (1.0 + math.exp(-12.0 * (t - 0.60))))),
        },
    ]

    if len(arc_definitions) != 20:
        raise ValueError(f"Expected exactly 20 energy arc curves, found {len(arc_definitions)}")

    arcs_spec: dict[str, EnergyArcCurveSpec] = {}
    for arc in arc_definitions:
        samples = [round(float(arc["fn"](pos)), 4) for pos in normalized_positions]
        arcs_spec[arc["id"]] = EnergyArcCurveSpec(
            id=arc["id"],
            name=arc["name"],
            formula=arc["formula"],
            description=arc["desc"],
            normalized_positions=normalized_positions,
            sampled_energy=samples,
            min_energy=min(samples),
            max_energy=max(samples),
        )

    return arcs_spec


def extract_biquad_validation() -> BiquadFilterRangesSpec:
    """Introspect PEQ and BiquadFilter model constraints."""
    field_freq = BiquadFilter.model_fields["frequency"]
    field_gain = BiquadFilter.model_fields["gain"]
    field_q = BiquadFilter.model_fields["q"]
    field_margin = PEQProfile.model_fields["safety_margin_db"]

    topologies = [ft.value for ft in FilterType]

    return BiquadFilterRangesSpec(
        frequency_hz={
            "min": float(field_freq.metadata[0].ge) if hasattr(field_freq.metadata[0], "ge") else 10.0,
            "max": float(field_freq.metadata[1].le) if hasattr(field_freq.metadata[1], "le") else 48000.0,
            "units": "Hz",
        },
        gain_db={
            "min": float(field_gain.metadata[0].ge) if hasattr(field_gain.metadata[0], "ge") else -48.0,
            "max": float(field_gain.metadata[1].le) if hasattr(field_gain.metadata[1], "le") else 48.0,
            "units": "dB",
        },
        q_factor={
            "min": float(field_q.metadata[0].gt) if hasattr(field_q.metadata[0], "gt") else 0.01,
            "max": float(field_q.metadata[1].le) if hasattr(field_q.metadata[1], "le") else 50.0,
            "units": "dimensionless",
        },
        headroom_margin_db=float(field_margin.default),
        supported_topologies=topologies,
    )


def extract_k_weighting_coefficients() -> KWeightingLoudnessSpec:
    """Generate exact ITU-R BS.1770-4 K-weighting biquad coefficients for 48 kHz and 44.1 kHz."""
    # 48 kHz (Official ITU-R BS.1770-4 Annex 1 Specification)
    # Stage 1: High-shelf pre-filter (head model)
    hs_48 = BiquadStageCoefficients(
        stage_name="Stage 1: High-Shelf Acoustic Head Model",
        topology="High-Shelf",
        b0=1.53512485958697,
        b1=-2.69169618940638,
        b2=1.19839281085285,
        a0=1.0,
        a1=-1.69065929318241,
        a2=0.73248077421585,
    )
    # Stage 2: RLB High-pass filter
    hp_48 = BiquadStageCoefficients(
        stage_name="Stage 2: RLB Weighting High-Pass Filter",
        topology="High-Pass",
        b0=1.0,
        b1=-2.0,
        b2=1.0,
        a0=1.0,
        a1=-1.99004745483398,
        a2=0.99007225036621,
    )

    # 44.1 kHz (Mapped Bilinear Transform Standard per libebur128 / EBU R128)
    hs_441 = BiquadStageCoefficients(
        stage_name="Stage 1: High-Shelf Acoustic Head Model",
        topology="High-Shelf",
        b0=1.5308412300498359,
        b1=-2.6509799951547285,
        b2=1.1690790799215918,
        a0=1.0,
        a1=-1.6636551132560204,
        a2=0.7125954280726244,
    )
    hp_441 = BiquadStageCoefficients(
        stage_name="Stage 2: RLB Weighting High-Pass Filter",
        topology="High-Pass",
        b0=1.0,
        b1=-2.0,
        b2=1.0,
        a0=1.0,
        a1=-1.9891696711779693,
        a2=0.989196395277732,
    )

    return KWeightingLoudnessSpec(
        description="Two-stage cascaded IIR biquad K-weighting filter for integrated LKFS/LUFS loudness measurement.",
        coefficients={
            "48000_hz": SampleRateKWeightingSpec(
                sample_rate_hz=48000,
                stage1_high_shelf=hs_48,
                stage2_high_pass=hp_48,
            ),
            "44100_hz": SampleRateKWeightingSpec(
                sample_rate_hz=44100,
                stage1_high_shelf=hs_441,
                stage2_high_pass=hp_441,
            ),
        },
    )


def generate_vibe_spec() -> VibeSpec:
    """Build, cross-validate, and return the complete VibeSpec object."""
    weights_spec = extract_algorithm_weights()
    presets_spec = extract_vibe_presets()
    derived_moods_spec = extract_derived_moods()
    camelot_spec = extract_camelot_system()
    energy_arcs_spec = extract_energy_arcs()
    biquad_spec = extract_biquad_validation()
    k_weighting_spec = extract_k_weighting_coefficients()

    spec = VibeSpec(
        algorithm_weights=weights_spec,
        vibe_presets=presets_spec,
        derived_moods=derived_moods_spec,
        camelot_harmonic_system=camelot_spec,
        energy_arcs=energy_arcs_spec,
        biquad_filter_validation=biquad_spec,
        k_weighting_loudness=k_weighting_spec,
    )

    return spec


def main() -> int:
    """Serialize the validated specification to assets/vibe_spec.json."""
    output_dir = PROJECT_ROOT / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    target_file = output_dir / "vibe_spec.json"

    print("[*] Introspecting codebase and assembling VibeSpec...")
    try:
        spec = generate_vibe_spec()
    except Exception as exc:
        print(f"[!] Specification assembly failed: {exc}", file=sys.stderr)
        return 1

    # Validate by exporting and re-reading
    json_str = spec.model_dump_json(indent=2)
    target_file.write_text(json_str, encoding="utf-8")
    print(f"[+] Wrote {len(json_str)} bytes to {target_file}")

    # Re-validate file on disk
    print(f"[*] Performing schema re-validation on {target_file.name}...")
    try:
        raw_data = json.loads(target_file.read_text(encoding="utf-8"))
        validated = VibeSpec.model_validate(raw_data)
        print(f"[✓] Schema verification SUCCESSFUL (Version {validated.schema_version})")
        print(f"    - Algorithm Weights: BPM={validated.algorithm_weights.bpm_harmonic_weight}")
        print(f"    - Vibe Presets: {len(validated.vibe_presets)} presets")
        print(f"    - Derived Moods: {len(validated.derived_moods)} formulas")
        print(f"    - Camelot System: 24 keys, {len(validated.camelot_harmonic_system.distance_matrix)}x{len(validated.camelot_harmonic_system.distance_matrix)} distance matrix")
        print(f"    - Energy Arcs: {len(validated.energy_arcs)} curves sampled at 11 positions")
        print(f"    - Biquad Validation: Fc {validated.biquad_filter_validation.frequency_hz['min']}-{validated.biquad_filter_validation.frequency_hz['max']} Hz, Gain +/-{validated.biquad_filter_validation.gain_db['max']} dB")
        print(f"    - K-Weighting: {len(validated.k_weighting_loudness.coefficients)} sample rates calibrated (48kHz & 44.1kHz)")
    except Exception as val_err:
        print(f"[!] Schema re-validation FAILED: {val_err}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
