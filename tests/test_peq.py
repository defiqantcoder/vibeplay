"""Unit tests for transducer PEQ engine, anti-clipping gain staging, and EasyEffects presets."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from typer.testing import CliRunner

from vibe_dsp.cli import app
from vibe_dsp.peq import (
    BiquadFilter,
    FilterType,
    PEQProfile,
    apply_headroom_calculation,
    apply_peq_preset,
    biquad_frequency_response,
    calculate_anti_clipping_preamp,
    calculate_composite_curve,
    export_easyeffects_preset,
    get_active_peq_state,
    ingest_peq_source,
    list_available_presets,
    lookup_autoeq_model,
    parse_autoeq_text,
    parse_json_filters,
    set_active_peq_state,
)

runner = CliRunner()

SAMPLE_AUTOEQ_TEXT = """
Preamp: -6.8 dB
Filter 1: ON PK Fc 28 Hz Gain 6.3 dB Q 0.54
Filter 2: ON PK Fc 193 Hz Gain -2.1 dB Q 0.88
Filter 3: ON PK Fc 1215 Hz Gain -2.0 dB Q 1.83
Filter 4: ON PK Fc 3108 Hz Gain 3.8 dB Q 2.05
Filter 5: ON PK Fc 5727 Hz Gain -6.4 dB Q 2.65
Filter 6: ON PK Fc 7962 Hz Gain 4.8 dB Q 2.92
Filter 7: ON LSC Fc 105 Hz Gain 5.5 dB Q 0.71
Filter 8: ON HSC Fc 10000 Hz Gain -2.0 dB Q 0.71
Filter 9: OFF PK Fc 14000 Hz Gain 1.0 dB Q 2.0
"""


def test_parse_autoeq_text() -> None:
    """Verify AutoEq / Squiglink parametric text parsing."""
    profile = parse_autoeq_text(SAMPLE_AUTOEQ_TEXT, name="Test IEM")

    assert profile.name == "Test IEM"
    assert profile.explicit_preamp == -6.8
    assert len(profile.filters) == 9
    assert len(profile.active_filters) == 8

    # Filter 1: PK 28Hz, +6.3dB, Q 0.54
    f1 = profile.filters[0]
    assert f1.enabled is True
    assert f1.filter_type == FilterType.PEAK
    assert f1.frequency == 28.0
    assert f1.gain == 6.3
    assert f1.q == 0.54

    # Filter 7: LSC 105Hz, +5.5dB, Q 0.71
    f7 = profile.filters[6]
    assert f7.filter_type == FilterType.LOW_SHELF
    assert f7.frequency == 105.0
    assert f7.gain == 5.5

    # Filter 9: Disabled
    f9 = profile.filters[8]
    assert f9.enabled is False


def test_parse_json_filters() -> None:
    """Verify parsing of user-defined JSON filter chains and EasyEffects JSON."""
    json_dict = {
        "name": "Custom Harman Target",
        "preamp": -4.2,
        "filters": [
            {"type": "PK", "frequency": 1000.0, "gain": 3.5, "q": 1.41},
            {"type": "Low-shelf", "frequency": 120.0, "gain": 4.0, "q": 0.71},
        ],
    }
    p1 = parse_json_filters(json_dict)
    assert p1.name == "Custom Harman Target"
    assert p1.explicit_preamp == -4.2
    assert len(p1.filters) == 2
    assert p1.filters[0].gain == 3.5
    assert p1.filters[1].filter_type == FilterType.LOW_SHELF

    # List of dicts
    json_list = [
        {"type": "High-shelf", "frequency": 8000.0, "gain": -2.5, "q": 0.71},
    ]
    p2 = parse_json_filters(json_list, name="Shelf Only")
    assert p2.name == "Shelf Only"
    assert len(p2.filters) == 1
    assert p2.filters[0].filter_type == FilterType.HIGH_SHELF


def test_biquad_frequency_response_peak() -> None:
    """Verify RBJ cookbook biquad frequency calculation at center frequency."""
    freqs = np.array([1000.0])
    mag = biquad_frequency_response(
        filter_type=FilterType.PEAK,
        f0=1000.0,
        gain_db=5.2,
        q=1.41,
        freqs=freqs,
        fs=48000.0,
    )
    assert pytest.approx(mag[0], abs=0.01) == 5.2


def test_biquad_frequency_response_low_shelf() -> None:
    """Verify low shelf filter response in passband and stopband."""
    freqs = np.array([20.0, 10000.0])
    mag = biquad_frequency_response(
        filter_type=FilterType.LOW_SHELF,
        f0=105.0,
        gain_db=4.0,
        q=0.71,
        freqs=freqs,
        fs=48000.0,
    )
    # Bass boost at 20 Hz should be ~4.0 dB
    assert pytest.approx(mag[0], abs=0.1) == 4.0
    # High frequency attenuation should be ~0 dB
    assert pytest.approx(mag[1], abs=0.1) == 0.0


def test_anti_clipping_headroom_calculation_single_filter() -> None:
    """Verify peak positive gain and negative digital pre-amplification calculation."""
    flt = BiquadFilter(
        filter_type=FilterType.PEAK,
        frequency=1000.0,
        gain=5.2,
        q=1.41,
    )
    peak, preamp = calculate_anti_clipping_preamp(filters=[flt], safety_margin_db=0.3)
    assert pytest.approx(peak, abs=0.05) == 5.2
    # Preamp should equal -(peak + 0.3) = -5.5 dB
    assert pytest.approx(preamp, abs=0.05) == -5.5


def test_anti_clipping_headroom_calculation_overlapping_filters() -> None:
    """Verify that overlapping positive filters sum up to higher peak gain."""
    flt1 = BiquadFilter(filter_type=FilterType.PEAK, frequency=1000.0, gain=3.0, q=1.0)
    flt2 = BiquadFilter(filter_type=FilterType.PEAK, frequency=1200.0, gain=3.0, q=1.0)

    peak, preamp = calculate_anti_clipping_preamp(filters=[flt1, flt2], safety_margin_db=0.3)
    # Overlapping filters must yield a composite peak higher than 3.0 dB
    assert peak > 3.0
    assert preamp == -round(peak + 0.3, 2)


def test_anti_clipping_headroom_calculation_negative_only() -> None:
    """Verify negative-only filters require zero preamp reduction."""
    flt = BiquadFilter(filter_type=FilterType.PEAK, frequency=3000.0, gain=-5.0, q=2.0)
    peak, preamp = calculate_anti_clipping_preamp(filters=[flt], safety_margin_db=0.3)
    assert peak == 0.0
    assert preamp == 0.0


def test_export_easyeffects_preset(tmp_path: Path) -> None:
    """Verify EasyEffects preset JSON export and automatic rollback script generation."""
    profile = parse_autoeq_text(SAMPLE_AUTOEQ_TEXT, name="Moondrop Test")
    preset_dir = tmp_path / "easyeffects" / "output"
    backup_dir = tmp_path / "backups"

    with patch("vibe_dsp.backup.DEFAULT_BACKUP_ROOT", backup_dir):
        preset_file, rollback_sh = export_easyeffects_preset(
            profile=profile,
            target_dir=preset_dir,
            backup=True,
        )

    assert preset_file.exists()
    assert rollback_sh is not None
    assert rollback_sh.exists()

    data = json.loads(preset_file.read_text(encoding="utf-8"))
    assert "output" in data
    assert "equalizer#0" in data["output"]
    eq = data["output"]["equalizer#0"]
    assert eq["input-gain"] == profile.calculated_preamp
    assert "band0" in eq["left"]
    assert eq["left"]["band0"]["type"] == "Bell"


def test_apply_peq_preset_lifecycle(tmp_path: Path) -> None:
    """Verify loading, toggling, and unloading of PEQ presets."""
    state_file = tmp_path / "active_peq.json"
    preset_dir = tmp_path / "output"
    preset_dir.mkdir(parents=True, exist_ok=True)

    dummy_preset = {
        "output": {
            "equalizer#0": {
                "input-gain": -6.5,
                "num-bands": 5,
                "left": {},
            }
        }
    }
    (preset_dir / "test_preset.json").write_text(json.dumps(dummy_preset), encoding="utf-8")

    # Mock subprocess.run for easyeffects CLI
    with patch("subprocess.run") as mock_sub:
        with patch("shutil.which", return_value="/usr/bin/easyeffects"):
            mock_sub.return_value.returncode = 0

            # 1. Load preset
            success, msg, state = apply_peq_preset(
                "test_preset",
                presets_dir=preset_dir,
                state_file=state_file,
            )
            assert success is True
            assert state["is_active"] is True
            assert state["active_profile"] == "test_preset"
            assert state["preamp_db"] == -6.5
            mock_sub.assert_called_with(
                ["/usr/bin/easyeffects", "-l", "test_preset"],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )

            # 2. Toggle active preset -> should unload
            success, msg, state = apply_peq_preset(
                "test_preset",
                toggle=True,
                presets_dir=preset_dir,
                state_file=state_file,
            )
            assert success is True
            assert state["is_active"] is False
            assert state["active_profile"] is None
            mock_sub.assert_called_with(
                ["/usr/bin/easyeffects", "--reset"],
                capture_output=True,
                text=True,
                check=False,
            )

            # 3. Explicit unload
            success, msg, state = apply_peq_preset(
                "test_preset",
                unload=True,
                presets_dir=preset_dir,
                state_file=state_file,
            )
            assert success is True
            assert state["is_active"] is False


def test_lookup_autoeq_model_bundled() -> None:
    """Verify lookup of bundled reference transducer profiles."""
    p1 = lookup_autoeq_model("Moondrop Blessing 2")
    assert p1 is not None
    assert "Blessing 2" in p1.name
    assert len(p1.filters) > 0

    p2 = lookup_autoeq_model("sennheiser_hd600")
    assert p2 is not None
    assert "Hd600" in p2.name or "HD600" in p2.name


def test_peq_cli_generate_json() -> None:
    """Verify vibe-dsp peq generate CLI command with --json output."""
    res = runner.invoke(app, ["peq", "generate", "--model", "Moondrop Blessing 2", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.stdout)
    assert "filters" in data
    assert "calculated_preamp" in data
    assert data["calculated_preamp"] < 0
    assert "peak_positive_gain" in data


def test_peq_cli_list_and_show() -> None:
    """Verify vibe-dsp peq list and vibe-dsp peq show CLI commands."""
    res_list = runner.invoke(app, ["peq", "list", "--json"])
    assert res_list.exit_code == 0
    data_list = json.loads(res_list.stdout)
    assert isinstance(data_list, list)
    assert len(data_list) > 0

    res_show = runner.invoke(app, ["peq", "show", "moondrop_blessing_2", "--json"])
    assert res_show.exit_code == 0
    data_show = json.loads(res_show.stdout)
    assert "filters" in data_show
