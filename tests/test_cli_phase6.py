"""Tests for Phase 6 CLI commands: playlist, export, and play."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

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


def test_cli_playlist_generate_and_export(tmp_path: Path, seed_test_database: Callable[[Path], list[int]]) -> None:
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


def test_cli_export_command(tmp_path: Path, seed_test_database: Callable[[Path], list[int]]) -> None:
    """Verify vibeplay export exports an existing playlist."""
    db_file = tmp_path / "cli_test.db"
    seed_test_database(db_file)

    # First generate playlist ID 1
    runner.invoke(app, ["playlist", "--seed", "1", "--limit", "3", "--db", str(db_file)])

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


def test_cli_play_command_mocked(tmp_path: Path, seed_test_database: Callable[[Path], list[int]]) -> None:
    """Verify vibeplay play communicates with MPD transport."""
    db_file = tmp_path / "cli_test.db"
    seed_test_database(db_file)

    # Generate playlist 1
    runner.invoke(app, ["playlist", "--seed", "1", "--limit", "3", "--db", str(db_file)])

    with patch("vibeplay.player.MPDClient") as mock_mpd:
        mock_client = MagicMock()
        mock_mpd.return_value = mock_client
        mock_client.status.return_value = {"state": "play"}

        result = runner.invoke(app, ["play", "--playlist-id", "1", "--db", str(db_file)])
        assert result.exit_code == 0, result.stdout
        assert "Playing Playlist:" in result.stdout


def test_cli_play_without_args_fails(tmp_path: Path) -> None:
    """Verify vibeplay play without --playlist-id or --seed fails with error."""
    db_file = tmp_path / "cli_test.db"
    result = runner.invoke(app, ["play", "--db", str(db_file)])
    assert result.exit_code == 1
    assert "Must specify either --playlist-id or --seed" in result.stdout


def test_cli_control_play_pause() -> None:
    """Verify vibeplay control play-pause toggles MPD playback state."""
    with patch("vibeplay.player.MPDClient") as mock_mpd:
        mock_client = MagicMock()
        mock_mpd.return_value = mock_client
        mock_client.status.return_value = {"state": "play"}

        result = runner.invoke(app, ["control", "play-pause"])
        assert result.exit_code == 0
        mock_client.pause.assert_called_once_with(1)
        assert "Playback paused" in result.stdout

        mock_client.reset_mock()
        mock_client.status.return_value = {"state": "pause"}
        result2 = runner.invoke(app, ["control", "play-pause"])
        assert result2.exit_code == 0
        mock_client.play.assert_called_once()
        assert "Playback started" in result2.stdout


def test_cli_control_actions() -> None:
    """Verify vibeplay control subactions (play, pause, stop, next, prev)."""
    with patch("vibeplay.player.MPDClient") as mock_mpd:
        mock_client = MagicMock()
        mock_mpd.return_value = mock_client

        assert runner.invoke(app, ["control", "play"]).exit_code == 0
        mock_client.play.assert_called_once()

        assert runner.invoke(app, ["control", "pause"]).exit_code == 0
        mock_client.pause.assert_called_once_with(1)

        assert runner.invoke(app, ["control", "stop"]).exit_code == 0
        mock_client.stop.assert_called_once()

        assert runner.invoke(app, ["control", "next"]).exit_code == 0
        mock_client.next.assert_called_once()

        assert runner.invoke(app, ["control", "previous"]).exit_code == 0
        mock_client.previous.assert_called_once()

        invalid_result = runner.invoke(app, ["control", "invalid-action"])
        assert invalid_result.exit_code == 1
        assert "Unknown control action" in invalid_result.stdout


def test_cli_web_help() -> None:
    """Verify vibeplay web alias shows help properly."""
    result = runner.invoke(app, ["web", "--help"])
    assert result.exit_code == 0
    assert "Alias for serve" in result.stdout


@patch("vibeplay.db.cleanup_expired_caches")
def test_cli_cache_cleanup(mock_cleanup: MagicMock) -> None:
    """Verify vibeplay cache cleanup calls cleanup_expired_caches."""
    mock_cleanup.return_value = {"llm_cache": 5, "network_cache": 10}
    result = runner.invoke(app, ["cache", "cleanup", "--days", "15"])
    assert result.exit_code == 0
    assert "Cache cleanup completed" in result.stdout
    assert "LLM Prompts Pruned:     5" in result.stdout
    assert "Network Records Pruned: 10" in result.stdout
    assert mock_cleanup.called
    kwargs = mock_cleanup.call_args.kwargs
    assert kwargs.get("max_age_days") == 15


@patch("vibeplay.db.purge_all_caches")
def test_cli_cache_purge_yes(mock_purge: MagicMock) -> None:
    """Verify vibeplay cache purge --yes calls purge_all_caches."""
    mock_purge.return_value = {"llm_cache": 50, "network_cache": 100}
    result = runner.invoke(app, ["cache", "purge", "--yes"])
    assert result.exit_code == 0
    assert "All caches purged" in result.stdout
    assert "LLM Prompts Deleted:     50" in result.stdout
    assert "Network Records Deleted: 100" in result.stdout
    assert mock_purge.called


def test_cli_cache_purge_abort() -> None:
    """Verify vibeplay cache purge aborts without --yes."""
    result = runner.invoke(app, ["cache", "purge"], input="n\n")
    assert result.exit_code == 0
    assert "Aborted." in result.stdout
