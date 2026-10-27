"""Tests for scripts/export_spec.py and assets/vibe_spec.json validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_spec import (
    VibeSpec,
)


def test_export_spec_script_execution() -> None:
    """Verify that python scripts/export_spec.py executes successfully with return code 0."""
    script_path = PROJECT_ROOT / "scripts" / "export_spec.py"
    assert script_path.exists(), "scripts/export_spec.py must exist"

    cmd = [sys.executable, str(script_path)]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)

    assert result.returncode == 0, f"Script failed with output:\n{result.stderr}\n{result.stdout}"
    assert "Schema verification SUCCESSFUL" in result.stdout

    spec_file = PROJECT_ROOT / "assets" / "vibe_spec.json"
    assert spec_file.exists(), "assets/vibe_spec.json must be created by the script"


def test_vibe_spec_schema_and_integrity() -> None:
    """Verify assets/vibe_spec.json adheres strictly to VibeSpec schema."""
    spec_file = PROJECT_ROOT / "assets" / "vibe_spec.json"
    assert spec_file.exists()

    raw_data = json.loads(spec_file.read_text(encoding="utf-8"))
    validated = VibeSpec.model_validate(raw_data)

    # 1. Algorithm Weights
    weights = validated.algorithm_weights
    assert weights.bpm_harmonic_weight == 0.8
    assert "circular_harmonic_bpm" in weights.relative_weight_vs_absolute_weight
    assert "standardized_absolute_bpm" in weights.relative_weight_vs_absolute_weight
    assert weights.column_weights["bpm"] == 1.0
    assert weights.column_weights["loudness"] == 0.5
    assert weights.column_weights["danceability"] == 1.0
    assert weights.column_weights["energy"] == 1.0
    assert weights.column_weights["mood"] == 1.0
    assert weights.column_weights["embedding"] == 0.8
    assert len(weights.heuristic_mood_keys) == 7
    assert weights.embedding_dimension == 64

    # 2. Vibe Presets (at least 20)
    assert len(validated.vibe_presets) >= 20
    assert "chill" in validated.vibe_presets
    assert "energetic" in validated.vibe_presets
    assert "workout" in validated.vibe_presets
    assert "melancholic" in validated.vibe_presets
    assert "euphoric" in validated.vibe_presets
    assert "deep_focus" in validated.vibe_presets
    assert "dark_intense" in validated.vibe_presets
    assert "ambient" in validated.vibe_presets
    assert "lofi" in validated.vibe_presets
    assert "driving" in validated.vibe_presets

    # 3. Derived Moods (exactly 8)
    assert len(validated.derived_moods) == 8
    expected_derived = {
        "chill",
        "energetic",
        "workout",
        "melancholic",
        "euphoric",
        "deep_focus",
        "dark_intense",
        "ambient",
    }
    assert set(validated.derived_moods.keys()) == expected_derived
    for mood in validated.derived_moods.values():
        assert len(mood.coefficients) > 0
        assert mood.formula != ""

    # 4. Camelot Key Conversion Wheel, Distance Matrix, Transition Scores
    camelot = validated.camelot_harmonic_system
    assert len(camelot.major_keys) >= 12
    assert len(camelot.minor_keys) >= 12
    assert camelot.transition_scores["exact_key_match_dist_0"] == 1.0
    assert camelot.transition_scores["harmonic_consonant_or_relative_dist_1"] == 0.95
    assert camelot.transition_scores["energy_whole_step_dist_2"] == 0.70
    assert camelot.transition_scores["moderate_leap_dist_3"] == 0.50
    assert camelot.transition_scores["dissonant_clash_dist_4_plus"] == 0.20

    # 24x24 distance matrix
    assert len(camelot.distance_matrix) == 24
    for k1, row in camelot.distance_matrix.items():
        assert len(row) == 24
        assert row[k1] == 0  # Distance to self is 0

    # 5. Energy Arcs (exactly 20, sampled at 11 positions)
    assert len(validated.energy_arcs) == 20
    for arc_id, arc in validated.energy_arcs.items():
        assert len(arc.normalized_positions) == 11
        assert len(arc.sampled_energy) == 11
        assert arc.normalized_positions == [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        for val in arc.sampled_energy:
            assert 0.0 <= val <= 1.0

    # 6. Biquad Filter Validation Ranges and Headroom
    biquad = validated.biquad_filter_validation
    assert biquad.frequency_hz["min"] == 10.0
    assert biquad.frequency_hz["max"] == 48000.0
    assert biquad.gain_db["min"] == -48.0
    assert biquad.gain_db["max"] == 48.0
    assert biquad.q_factor["min"] == 0.01
    assert biquad.q_factor["max"] == 50.0
    assert biquad.headroom_margin_db == 0.3
    assert "PK" in biquad.supported_topologies

    # 7. ITU-R BS.1770-4 K-weighting biquad coefficients
    k_weight = validated.k_weighting_loudness
    assert "48000_hz" in k_weight.coefficients
    assert "44100_hz" in k_weight.coefficients

    coef_48 = k_weight.coefficients["48000_hz"]
    assert pytest.approx(coef_48.stage1_high_shelf.b0, rel=1e-5) == 1.53512485958697
    assert pytest.approx(coef_48.stage1_high_shelf.a1, rel=1e-5) == -1.69065929318241
    assert pytest.approx(coef_48.stage2_high_pass.b0, rel=1e-5) == 1.0
    assert pytest.approx(coef_48.stage2_high_pass.a1, rel=1e-5) == -1.99004745483398

    coef_441 = k_weight.coefficients["44100_hz"]
    assert pytest.approx(coef_441.stage1_high_shelf.b0, rel=1e-5) == 1.530841230049836
    assert pytest.approx(coef_441.stage1_high_shelf.a1, rel=1e-5) == -1.6636551132560204
    assert pytest.approx(coef_441.stage2_high_pass.b0, rel=1e-5) == 1.0
    assert pytest.approx(coef_441.stage2_high_pass.a1, rel=1e-5) == -1.9891696711779694


def test_vibe_spec_missing_fields_validation_failure() -> None:
    """Verify that omitting required fields raises ValidationError."""
    spec_file = PROJECT_ROOT / "assets" / "vibe_spec.json"
    raw_data = json.loads(spec_file.read_text(encoding="utf-8"))

    # Missing top-level key
    corrupted = dict(raw_data)
    del corrupted["algorithm_weights"]
    with pytest.raises(ValidationError):
        VibeSpec.model_validate(corrupted)

    # Missing sub-key in algorithm_weights
    corrupted = dict(raw_data)
    corrupted_weights = dict(raw_data["algorithm_weights"])
    del corrupted_weights["bpm_harmonic_weight"]
    corrupted["algorithm_weights"] = corrupted_weights
    with pytest.raises(ValidationError):
        VibeSpec.model_validate(corrupted)

    # Invalid energy arc sample length (< 11)
    corrupted = dict(raw_data)
    corrupted_arcs = dict(raw_data["energy_arcs"])
    corrupted_ramp = dict(corrupted_arcs["energy_ramp"])
    corrupted_ramp["sampled_energy"] = [0.1, 0.2, 0.3]  # Only 3 samples
    corrupted_arcs["energy_ramp"] = corrupted_ramp
    corrupted["energy_arcs"] = corrupted_arcs
    with pytest.raises(ValidationError):
        VibeSpec.model_validate(corrupted)
