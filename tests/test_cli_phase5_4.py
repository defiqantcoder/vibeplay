"""Integration tests for vibe-dsp Phase 5.4 CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from vibe_dsp.cli import app

runner = CliRunner()


def test_cli_spatial_setup_dry_run(tmp_path: Path) -> None:
    """Verify vibe-dsp spatial setup --dry-run outputs configuration preview without writing files."""
    sofa_file = tmp_path / "test.sofa"
    sofa_file.write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 1024)

    result = runner.invoke(app, ["spatial", "setup", "--sofa", str(sofa_file), "--dry-run"])
    assert result.exit_code == 0
    assert "PipeWire 7.1.4 Spatial Binaural Virtualization Setup" in result.stdout
    assert "DRY RUN MODE" in result.stdout
    assert "Spatial-7.1.4-Sink" in result.stdout
    assert "FL FR FC LFE SL SR BL BR TFL TFR TBL TBR" in result.stdout


def test_cli_spatial_status() -> None:
    """Verify vibe-dsp spatial status displays state table."""
    result = runner.invoke(app, ["spatial", "status"])
    assert result.exit_code == 0
    assert "Spatial Virtualization Status" in result.stdout
    assert "Spatial-7.1.4-Sink" in result.stdout


def test_cli_spatial_toggle() -> None:
    """Verify vibe-dsp spatial toggle switches mode."""
    with patch("vibe_dsp.cli.set_spatial_virtualization_mode", return_value=True):
        result = runner.invoke(app, ["spatial", "toggle", "--mode", "3d_binaural"])
        assert result.exit_code == 0
        assert "Spatial Mode Updated" in result.stdout


def test_cli_route_passthrough_all() -> None:
    """Verify vibe-dsp route passthrough --all enables receiver codecs."""
    with patch(
        "vibe_dsp.cli.configure_sink_passthrough",
        return_value=(True, "Configured passthrough"),
    ):
        with patch("vibe_dsp.cli.discover_receiver_endpoints", return_value=[MagicMock(sink_id="test", sink_name="test", description="test", supported_codecs=["ac3"])]): result = runner.invoke(app, ["route", "passthrough", "--all", "--no-default"])
        assert result.exit_code == 0
        assert "Receiver Bitstream Passthrough Setup" in result.stdout
        assert "Success" in result.stdout


def test_cli_profile_management() -> None:
    """Verify vibe-dsp profile list, get, and set commands."""
    # profile list
    res_list = runner.invoke(app, ["profile", "list"])
    assert res_list.exit_code == 0
    assert "pure-bitperfect" in res_list.stdout
    assert "spatial-headphones" in res_list.stdout
    assert "receiver-passthrough" in res_list.stdout

    # profile get
    res_get = runner.invoke(app, ["profile", "get"])
    assert res_get.exit_code == 0
    assert "Active Audio Profile" in res_get.stdout

    # profile set pure-bitperfect
    with patch("vibe_dsp.ipc.switch_audio_profile", return_value={"status": "ok", "message": "Success"}):
        res_set = runner.invoke(app, ["profile", "set", "pure-bitperfect"])
        assert res_set.exit_code == 0
        assert "Success" in res_set.stdout
