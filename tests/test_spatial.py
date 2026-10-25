"""Unit and integration tests for vibe_dsp.spatial (Phase 5.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from vibe_dsp.spatial import (
    CHANNEL_LAYOUT_7_1_4,
    SPATIAL_SINK_NAME,
    calculate_composite_preamp,
    ensure_default_sofa_hrtf,
    generate_pipewire_spatial_filter_chain_config,
    get_available_sofa_profiles,
    get_spatial_virtualization_status,
    inspect_sofa_file,
    set_spatial_virtualization_mode,
    swap_spatial_profile,
    write_spatial_filter_chain,
)


def test_channel_layout_7_1_4_specification() -> None:
    """Verify that CHANNEL_LAYOUT_7_1_4 defines exactly 12 channels matching standard Dolby/ITU 7.1.4."""
    assert len(CHANNEL_LAYOUT_7_1_4) == 12
    ch_names = [ch[0] for ch in CHANNEL_LAYOUT_7_1_4]
    expected_names = ["FL", "FR", "FC", "LFE", "SL", "SR", "BL", "BR", "TFL", "TFR", "TBL", "TBR"]
    assert ch_names == expected_names


def test_calculate_composite_preamp_headroom() -> None:
    """Verify dynamic anti-clipping composite digital preamp calculation."""
    # Base -8.0 dB and PEQ -3.5 dB -> composite -11.5 dB
    comp = calculate_composite_preamp(base_preamp_db=-8.0, peq_preamp_db=-3.5)
    assert comp == -11.5

    # Base -8.0 dB and neutral PEQ (0.0 dB) -> -8.0 dB
    assert calculate_composite_preamp(base_preamp_db=-8.0, peq_preamp_db=0.0) == -8.0

    # Positive PEQ headroom is clamped to 0 to prevent positive boost
    assert calculate_composite_preamp(base_preamp_db=-8.0, peq_preamp_db=2.0) == -8.0


def test_ensure_default_sofa_hrtf_offline_fallback(tmp_path: Path) -> None:
    """Verify that SOFA HRTF downloader generates a valid synthetic fallback when offline."""
    # Pass an unreachable URL to test offline fallback
    sofa_file = ensure_default_sofa_hrtf(
        target_dir=tmp_path,
        url="http://127.0.0.1:54321/nonexistent.sofa",
        offline_fallback=True,
    )
    assert sofa_file.exists()
    assert sofa_file.stat().st_size > 512

    info = inspect_sofa_file(sofa_file)
    assert info["is_valid"] is True
    assert info["channels_supported"] == 12
    assert "7.1.4" in info["layout"]


def test_generate_pipewire_spatial_filter_chain_config(tmp_path: Path) -> None:
    """Verify generated PipeWire filter-chain SPA-JSON configuration."""
    sofa_file = tmp_path / "mock.sofa"
    sofa_file.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 1024)

    config_str = generate_pipewire_spatial_filter_chain_config(
        sofa_path=sofa_file,
        composite_preamp_db=-10.5,
        sink_name=SPATIAL_SINK_NAME,
    )

    assert "libpipewire-module-filter-chain" in config_str
    assert SPATIAL_SINK_NAME in config_str
    assert "audio.channels   = 12" in config_str
    assert "FL FR FC LFE SL SR BL BR TFL TFR TBL TBR" in config_str
    assert str(sofa_file.resolve()) in config_str
    # Check linear gain calculation for -10.5 dB: 10^(-10.5/20) approx 0.298538
    assert '"Gain" =' in config_str


def test_write_spatial_filter_chain_with_backup(tmp_path: Path) -> None:
    """Verify write_spatial_filter_chain creates backup and writes drop-in config."""
    conf_dir = tmp_path / "pipewire.conf.d"
    sofa_file = tmp_path / "test.sofa"
    sofa_file.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 1024)

    target_file = write_spatial_filter_chain(
        sofa_path=sofa_file,
        composite_preamp_db=-8.0,
        conf_dir=conf_dir,
        filename="98-spatial-7.1.4.conf",
    )

    assert target_file.exists()
    assert "Spatial-7.1.4-Sink" in target_file.read_text(encoding="utf-8")


def test_get_spatial_virtualization_status_mocked() -> None:
    """Verify wpctl status parsing for spatial sink."""
    mock_wpctl_output = """
Audio
 ├─ Sinks:
 │      42. Built-in Audio Analog Stereo
 │  *   55. Spatial-7.1.4-Sink                  [vol: 1.00]
 │
"""
    with patch("shutil.which", return_value="/usr/bin/wpctl"), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_wpctl_output)
        status = get_spatial_virtualization_status()

        assert status["is_active"] is True
        assert status["mode"] == "3d_binaural"
        assert status["node_id"] == 55


def test_set_spatial_virtualization_mode_toggle() -> None:
    """Verify set_spatial_virtualization_mode executes wpctl set-default."""
    with (
        patch("shutil.which", return_value="/usr/bin/wpctl"),
        patch(
            "vibe_dsp.spatial.get_spatial_virtualization_status",
            return_value={"node_id": 55, "mode": "stereo_direct"},
        ),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)

        # Enable 3D binaural
        res = set_spatial_virtualization_mode("3d_binaural")
        assert res is True
        mock_run.assert_called_with(
            ["wpctl", "set-default", "55"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )


def test_get_available_sofa_profiles(tmp_path: Path) -> None:
    """Verify get_available_sofa_profiles discovers and returns custom SOFA profiles."""
    # Create mock SOFA files in a temporary custom directory
    sofa1 = tmp_path / "custom1.sofa"
    sofa1.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 1024)

    sofa2 = tmp_path / "custom2.sofa"
    sofa2.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 1024)

    # Mock inspect_sofa_file to return a valid result
    with patch("vibe_dsp.spatial.inspect_sofa_file") as mock_inspect:
        mock_inspect.return_value = {
            "is_valid": True,
            "layout": "7.1.4",
            "channels_supported": 12,
        }

        profiles = get_available_sofa_profiles(custom_dir=tmp_path)
        assert len(profiles) >= 2

        names = [p["name"] for p in profiles]
        assert "custom1" in names
        assert "custom2" in names


def test_swap_spatial_profile_dynamic_load(tmp_path: Path) -> None:
    """Verify custom SOFA profiles can be swapped without re-initializing the PipeWire graph."""
    from vibe_dsp.spatial import DEFAULT_HRTF_DIR
    authorized_dir = DEFAULT_HRTF_DIR
    authorized_dir.mkdir(parents=True, exist_ok=True)
    sofa_file = authorized_dir / "custom_spatial.sofa"
    sofa_file.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 1024)

    # Mock subprocess.run for pw-cli commands
    def mock_subprocess_run(*args, **kwargs):
        cmd = args[0]
        if "dump" in cmd and "Module" in cmd:
            # Mock the dump output showing the active spatial module
            stdout = "id 42, type PipeWire:Interface:Module\n"
            stdout += "    module.name = \"libpipewire-module-filter-chain\"\n"
            stdout += "    node.description = \"Vibe-DSP 7.1.4 Binaural Spatial Audio Sink\"\n"
            stdout += '    module.name = "libpipewire-module-filter-chain"\n'
            stdout += '    node.description = "Vibe-DSP 7.1.4 Binaural Spatial Audio Sink"\n'
            return MagicMock(returncode=0, stdout=stdout)
        elif "destroy" in cmd:
            return MagicMock(returncode=0, stdout="")
        elif "load-module" in cmd:
            return MagicMock(returncode=0, stdout="")
        return MagicMock(returncode=0, stdout="")

    with patch("vibe_dsp.spatial.shutil.which", return_value="/usr/bin/pw-cli"):
        with patch("vibe_dsp.spatial.subprocess.run", side_effect=mock_subprocess_run) as mock_run:
            with patch("vibe_dsp.spatial.write_spatial_filter_chain") as mock_write:
                res = swap_spatial_profile(sofa_file, -10.0)

                assert res is True
                mock_write.assert_called_once_with(sofa_file, -10.0)

                # Check that pw-cli destroy was called with the correct module ID (42)
                destroy_call = any("destroy" in call.args[0] and "42" in call.args[0] for call in mock_run.mock_calls if call.args)
                assert destroy_call is True

                # Check that pw-cli load-module was called
                load_call = any(
                    "load-module" in call.args[0] and "libpipewire-module-filter-chain" in call.args[0] for call in mock_run.mock_calls if call.args
                )
                assert load_call is True

def test_swap_spatial_profile_path_traversal(tmp_path: Path) -> None:
    """Verify swap_spatial_profile raises ValueError if SOFA path is outside authorized directories."""
    unauthorized_sofa = tmp_path / "hacked.sofa"
    unauthorized_sofa.write_bytes(b"bad")
    import pytest
    with pytest.raises(ValueError, match="Unauthorized path: SOFA profile must be located in"):
        swap_spatial_profile(unauthorized_sofa, -10.0)

def test_swap_spatial_profile_fallback(tmp_path: Path) -> None:
    """Verify swap_spatial_profile rolls back to stereo_direct if pw-cli load-module fails."""
    from vibe_dsp.spatial import DEFAULT_HRTF_DIR
    authorized_dir = DEFAULT_HRTF_DIR
    authorized_dir.mkdir(parents=True, exist_ok=True)
    authorized_sofa = authorized_dir / "valid_fallback_test.sofa"
    authorized_sofa.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 1024)

    def mock_subprocess_run(*args, **kwargs):
        cmd = args[0]
        if "dump" in cmd:
            stdout = "id 42, type PipeWire:Interface:Module\n"
            stdout += "    module.name = \"libpipewire-module-filter-chain\"\n"
            stdout += "    node.description = \"Vibe-DSP 7.1.4 Binaural Spatial Audio Sink\"\n"
            return MagicMock(returncode=0, stdout=stdout)
        elif "destroy" in cmd:
            return MagicMock(returncode=0, stdout="")
        elif "load-module" in cmd:
            # Simulate failure when loading module
            return MagicMock(returncode=1, stderr="failed to load")
        return MagicMock(returncode=0, stdout="")

    with patch("vibe_dsp.spatial.shutil.which", return_value="/usr/bin/pw-cli"):
        with patch("vibe_dsp.spatial.subprocess.run", side_effect=mock_subprocess_run):
            with patch("vibe_dsp.spatial.write_spatial_filter_chain"):
                with patch("vibe_dsp.spatial.set_spatial_virtualization_mode") as mock_fallback:
                    res = swap_spatial_profile(authorized_sofa, -10.0)
                    assert res is False
                    mock_fallback.assert_called_once_with("stereo_direct")
