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


def test_detect_codec_from_path() -> None:
    """Verify dynamic codec detection and lossless categorization from audio extensions."""
    from vibeplay.player import _detect_codec_from_path

    codec, is_lossless = _detect_codec_from_path("/music/track.flac")
    assert codec == "FLAC" and is_lossless is True

    codec, is_lossless = _detect_codec_from_path("/music/track.wav")
    assert codec == "WAV" and is_lossless is True

    codec, is_lossless = _detect_codec_from_path("/music/track.alac")
    assert codec == "ALAC" and is_lossless is True

    codec, is_lossless = _detect_codec_from_path("/music/track_alac.m4a")
    assert codec == "ALAC" and is_lossless is True

    codec, is_lossless = _detect_codec_from_path("/music/track.m4a")
    assert codec == "AAC" and is_lossless is False

    codec, is_lossless = _detect_codec_from_path("/music/track.mp3")
    assert codec == "MP3" and is_lossless is False

    codec, is_lossless = _detect_codec_from_path("/music/track.opus")
    assert codec == "OPUS" and is_lossless is False

    codec, is_lossless = _detect_codec_from_path("/music/track.ogg")
    assert codec == "OGG" and is_lossless is False


def test_playback_status_codec_and_bitperfect() -> None:
    """Verify dynamic codec, standby placeholder, and strict bit-perfect evaluation."""
    from vibeplay.player import get_playback_status

    # 1. Stopped / standby state returns "--"
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls:
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {"state": "stop", "volume": "100"}
        mock_client.currentsong.return_value = {}

        st = get_playback_status()
        assert st["state"] == "stop"
        assert st["sample_rate"] == "--"
        assert st["bit_depth"] == "--"
        assert st["audio_spec"] == "--"
        assert st["codec"] == "--"
        assert st["bit_perfect"] is False
        assert st["buffer_health"] == "Standby (Direct ALSA Ready)"

    # 2. Playing lossless FLAC at 100% volume with matching sample rate -> True bit-perfect
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls, patch(
        "vibeplay.player._extract_audio_file_technical_info",
        return_value={"sample_rate": 44100, "bit_depth": 16, "channels": 2, "codec": "FLAC", "format_name": "flac"},
    ):
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {
            "state": "play",
            "volume": "100",
            "audio": "44100:16:2",
            "time": "10:180",
        }
        mock_client.currentsong.return_value = {
            "file": "/music/song.flac",
            "title": "Song",
            "artist": "Artist",
        }

        st = get_playback_status()
        assert st["state"] == "play"
        assert st["codec"] == "FLAC"
        assert st["bit_perfect"] is True
        assert st["buffer_health"] == "100% Bit-Perfect Locked"

    # 3. Playing lossy MP3 -> bit_perfect is False, status is DSP / Processed
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls, patch(
        "vibeplay.player._extract_audio_file_technical_info",
        return_value={"sample_rate": 44100, "bit_depth": 16, "channels": 2, "codec": "MP3", "format_name": "mp3"},
    ):
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {
            "state": "play",
            "volume": "100",
            "audio": "44100:16:2",
            "time": "10:180",
        }
        mock_client.currentsong.return_value = {
            "file": "/music/song.mp3",
            "title": "Song",
            "artist": "Artist",
        }

        st = get_playback_status()
        assert st["codec"] == "MP3"
        assert st["bit_perfect"] is False
        assert st["buffer_health"] == "DSP / Processed"

    # 4. Playing lossless FLAC with software volume attenuation (80%) -> bit_perfect is False
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls, patch(
        "vibeplay.player._extract_audio_file_technical_info",
        return_value={"sample_rate": 44100, "bit_depth": 16, "channels": 2, "codec": "FLAC", "format_name": "flac"},
    ):
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {
            "state": "play",
            "volume": "80",
            "audio": "44100:16:2",
            "time": "10:180",
        }
        mock_client.currentsong.return_value = {
            "file": "/music/song.flac",
            "title": "Song",
            "artist": "Artist",
        }

        st = get_playback_status()
        assert st["bit_perfect"] is False
        assert st["buffer_health"] == "DSP / Processed"

    # 5. Playing lossless FLAC but with bit depth upsampled (16-bit to 24-bit) -> bit_perfect is False
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls, patch(
        "vibeplay.player._extract_audio_file_technical_info",
        return_value={"sample_rate": 44100, "bits_per_sample": 16, "channels": 2, "codec": "FLAC", "format_name": "flac"},
    ):
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {
            "state": "play",
            "volume": "100",
            "audio": "44100:24:2",
            "time": "10:180",
        }
        mock_client.currentsong.return_value = {
            "file": "/music/song.flac",
            "title": "Song",
            "artist": "Artist",
        }

        st = get_playback_status()
        assert st["bit_perfect"] is False
        assert st["buffer_health"] == "DSP / Processed"

    # 6. Playing lossless FLAC (stereo) but output is mono -> bit_perfect is False
    with patch("vibeplay.player.MPDClient") as mock_mpd_cls, patch(
        "vibeplay.player._extract_audio_file_technical_info",
        return_value={"sample_rate": 44100, "bits_per_sample": 16, "channels": 2, "codec": "FLAC", "format_name": "flac"},
    ):
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        mock_client.status.return_value = {
            "state": "play",
            "volume": "100",
            "audio": "44100:16:1",
            "time": "10:180",
        }
        mock_client.currentsong.return_value = {
            "file": "/music/song.flac",
            "title": "Song",
            "artist": "Artist",
        }

        st = get_playback_status()
        assert st["bit_perfect"] is False
        assert st["buffer_health"] == "DSP / Processed"


def test_direct_alsa_line_out_volume_safety() -> None:
    """Verify direct ALSA volume (-1) exposes fixed hardware line-out and catches setvol cleanly."""
    from vibeplay.player import adjust_volume_step, get_playback_status, set_volume_level, toggle_mute

    with patch("vibeplay.player.MPDClient") as mock_mpd_cls:
        mock_client = MagicMock()
        mock_mpd_cls.return_value = mock_client
        # volume: -1 indicates direct ALSA hardware with mixer_type "none"
        mock_client.status.return_value = {"state": "play", "volume": "-1", "audio": "96000:24:2"}
        mock_client.currentsong.return_value = {"file": "/music/highres.flac"}
        mock_client.setvol.side_effect = Exception("ACK [50@0] {setvol} problems setting volume")

        # Calling setvol / adjust volume should catch exception cleanly and return status dict
        vol = set_volume_level(80)
        assert isinstance(vol, dict)
        assert vol["volume"] == 80

        vol_adj = adjust_volume_step(5)
        assert isinstance(vol_adj, dict)

        mute_res = toggle_mute()
        assert isinstance(mute_res, dict)

        st = get_playback_status()
        assert st["volume"] == 100
        assert "0.0 dB (Hardware Line-Out)" in st["volume_db"]


def test_fallback_player_lifecycle_and_lock() -> None:
    """Verify _FALLBACK_LOCK prevents concurrent or orphaned fallback playback processes."""
    import subprocess

    import vibeplay.player as player_mod

    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    # Simulate wait() timeout expiring to test fallback kill() logic
    mock_proc.wait.side_effect = [subprocess.TimeoutExpired("aplay", 0.3), 0]

    with player_mod._FALLBACK_LOCK:
        player_mod._FALLBACK_PROC = mock_proc

    player_mod._stop_fallback_playback()

    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()
    assert player_mod._FALLBACK_PROC is None
