"""Tests for bit-perfect player queue transport wrapping python-mpd2."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibeplay.db import (
    add_tracks_to_playlist,
    create_playlist,
    get_connection,
    init_db,
    insert_track,
)
from vibeplay.player import MPDTransport, PlaybackError, play_playlist


@pytest.fixture
def player_test_db(tmp_path: Path) -> tuple[Path, int]:
    """Create a temporary database with tracks and a playlist for playback tests."""
    db_file = tmp_path / "test_player.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        insert_track(
            conn,
            path=str(tmp_path / "music" / "song1.flac"),
            mtime=1700000000.0,
            size=10000000,
            file_hash="ph1",
            duration=180.0,
            title="Song One",
            artist="Artist A",
            album="Album One",
        )
        insert_track(
            conn,
            path=str(tmp_path / "music" / "song2.flac"),
            mtime=1700000001.0,
            size=11000000,
            file_hash="ph2",
            duration=210.0,
            title="Song Two",
            artist="Artist B",
            album="Album Two",
        )
        pid = create_playlist(conn, name="Test Playback Queue")
        add_tracks_to_playlist(conn, pid, [1, 2])

    return db_file, pid


def test_mpd_transport_tcp_lifecycle() -> None:
    """Verify MPDTransport TCP connection, command sequencing, and disconnection."""
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls:
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {"state": "play", "song": "0"}
        mock_client.currentsong.return_value = {"file": "/music/song1.flac"}

        transport = MPDTransport(host="localhost", port=6600, timeout=5.0)
        transport.connect()
        mock_client.connect.assert_called_once_with("localhost", 6600)

        transport.clear()
        mock_client.clear.assert_called_once()

        added = transport.add_tracks(["/music/song1.flac", "/music/song2.flac"])
        assert added == 2
        assert mock_client.add.call_count == 2

        transport.play(0)
        mock_client.play.assert_called_once_with(0)

        status = transport.status()
        assert status["state"] == "play"

        curr = transport.current_song()
        assert curr["file"] == "/music/song1.flac"

        transport.disconnect()
        mock_client.close.assert_called_once()
        mock_client.disconnect.assert_called_once()


def test_mpd_transport_unix_socket() -> None:
    """Verify MPDTransport detects UNIX socket paths and connects via socket."""
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls:
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client

        socket_path = "/run/user/1000/mpd/socket"
        transport = MPDTransport(host=socket_path)
        transport.connect()
        mock_client.connect.assert_called_once_with(socket_path)


def test_mpd_transport_connection_failure() -> None:
    """Verify PlaybackError is raised when MPD daemon connection fails."""
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls:
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.connect.side_effect = ConnectionRefusedError("Connection refused")

        transport = MPDTransport(host="localhost", port=6600)
        with pytest.raises(
            PlaybackError, match="Could not connect to Music Player Daemon"
        ):
            transport.connect()


def test_play_playlist_success(player_test_db: tuple[Path, int]) -> None:
    """Verify play_playlist queries tracks, queues them into MPD, and triggers playback."""
    db_file, pid = player_test_db

    with patch("vibeplay.player.MPDClient") as mock_mpd_cls:
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {"state": "play"}

        result = play_playlist(db_file, pid)

        assert result["playlist_id"] == pid
        assert result["queued_tracks"] == 2
        mock_client.clear.assert_called_once()
        assert mock_client.add.call_count == 2
        mock_client.play.assert_called_once_with(0)


def test_play_playlist_nonexistent_raises(player_test_db: tuple[Path, int]) -> None:
    """Verify ValueError when attempting to play an unknown playlist ID."""
    db_file, _ = player_test_db
    with pytest.raises(ValueError, match="Playlist with ID 999 not found"):
        play_playlist(db_file, 999)


def test_adjust_volume_step_and_mute() -> None:
    """Verify volume stepping and mute toggle behavior with MPDClient."""
    from vibeplay.player import adjust_volume_step, set_volume_level, toggle_mute

    with patch("vibeplay.player.MPDClient") as mock_mpd_cls:
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        vol_state = {"volume": "75"}
        mock_client.status.side_effect = lambda: dict(vol_state)

        def fake_setvol(v: int) -> None:
            vol_state["volume"] = str(v)

        mock_client.setvol.side_effect = fake_setvol

        # Set initial volume
        set_volume_level(75)
        assert vol_state["volume"] == "75"

        # Step up by 5
        adjust_volume_step(5)
        assert vol_state["volume"] == "80"

        # Step down by 10
        adjust_volume_step(-10)
        assert vol_state["volume"] == "70"

        # Toggle mute: should set to 0
        toggle_mute()
        assert vol_state["volume"] == "0"

        # Toggle unmute: should restore last volume (70)
        toggle_mute()
        assert vol_state["volume"] == "70"
