"""Tests for Phase 6 CLI commands: playlist, export, and play."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typing import Callable
from typer.testing import CliRunner

from vibeplay.cli import app

runner = CliRunner()


def test_cli_playlist_help() -> None:
    """Verify vibeplay playlist --help outputs options and flags."""
    result = runner.invoke(app, ["playlist", "--help"])
    assert result.exit_code == 0
    assert "--seed" in result.stdout
    assert "--cluster" in result.stdout
    assert "--vibe" in result.stdout
    assert "--arc" in result.stdout
    assert "--limit" in result.stdout
    assert "--export-m3u8" in result.stdout
    assert "--play" in result.stdout


def test_cli_export_help() -> None:
    """Verify vibeplay export --help outputs options."""
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "playlist_id" in result.stdout
    assert "--out" in result.stdout
    assert "--format" in result.stdout


def test_cli_play_help() -> None:
    """Verify vibeplay play --help outputs options."""
    result = runner.invoke(app, ["play", "--help"])
    assert result.exit_code == 0
    assert "--playlist-id" in result.stdout
    assert "--seed" in result.stdout


def test_cli_playlist_generate_and_export(
    tmp_path: Path, seed_test_database: Callable[[Path], list[int]]
) -> None:
    """Verify vibeplay playlist runs end-to-end and creates playlist and M3U8."""
    db_file = tmp_path / "cli_test.db"
    seed_test_database(db_file)
    m3u8_out = tmp_path / "cli_exported.m3u8"

    result = runner.invoke(
        app,
        [
            "playlist",
            "--seed",
            "1",
            "--limit",
            "4",
            "--export-m3u8",
            str(m3u8_out),
            "--db",
            str(db_file),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Playlist Saved:" in result.stdout
    assert "Exported M3U8:" in result.stdout
    assert m3u8_out.exists()


def test_cli_export_command(
    tmp_path: Path, seed_test_database: Callable[[Path], list[int]]
) -> None:
    """Verify vibeplay export exports an existing playlist."""
    db_file = tmp_path / "cli_test.db"
    seed_test_database(db_file)

    # First generate playlist ID 1
    runner.invoke(
        app, ["playlist", "--seed", "1", "--limit", "3", "--db", str(db_file)]
    )

    json_out = tmp_path / "out.json"
    result = runner.invoke(
        app,
        [
            "export",
            "1",
            "--out",
            str(json_out),
            "--format",
            "json",
            "--db",
            str(db_file),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Playlist Exported:" in result.stdout
    assert json_out.exists()


def test_cli_play_command_mocked(
    tmp_path: Path, seed_test_database: Callable[[Path], list[int]]
) -> None:
    """Verify vibeplay play communicates with MPD transport."""
    db_file = tmp_path / "cli_test.db"
    seed_test_database(db_file)

    # Generate playlist 1
    runner.invoke(
        app, ["playlist", "--seed", "1", "--limit", "3", "--db", str(db_file)]
    )

    with patch("vibeplay.player.MPDClient") as mock_mpd:
        mock_client = MagicMock()
        mock_mpd.return_value = mock_client
        mock_client.status.return_value = {"state": "play"}

        result = runner.invoke(
            app, ["play", "--playlist-id", "1", "--db", str(db_file)]
        )
        assert result.exit_code == 0, result.stdout
        assert "Playing Playlist:" in result.stdout


def test_cli_play_without_args_fails(tmp_path: Path) -> None:
    """Verify vibeplay play without --playlist-id or --seed fails with error."""
    db_file = tmp_path / "cli_test.db"
    result = runner.invoke(app, ["play", "--db", str(db_file)])
    assert result.exit_code == 1
    assert "Must specify either --playlist-id or --seed" in result.stdout
