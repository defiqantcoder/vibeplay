"""Tests for Phase 6 MIME/URI handling, single-instance IPC forwarding, and SSE telemetry streaming."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db
from vibeplay.desktop.__main__ import main as desktop_main
from vibeplay.desktop.mime import (
    MIME_TYPE_ASSOCIATIONS,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_PLAYLIST_EXTENSIONS,
    classify_mime_target,
    forward_uris_to_running_instance,
    parse_desktop_uri,
    parse_m3u_playlist,
)
from vibeplay.web import create_app


@pytest.fixture
def isolated_env(tmp_path: Path):
    """Create an isolated SQLite DB and desktop settings path for Phase 6 tests."""
    db_path = tmp_path / "test_phase6.db"
    settings_path = tmp_path / "desktop_settings.json"
    music_dir = tmp_path / "music"
    music_dir.mkdir(parents=True, exist_ok=True)

    init_db(db_path)
    cfg = Settings(
        db_path=db_path,
        desktop_settings_path=settings_path,
    )
    return db_path, settings_path, music_dir, cfg


def test_parse_desktop_uri_local_and_file_scheme(tmp_path: Path) -> None:
    """Verify parse_desktop_uri handles local paths, file:// URIs, and URL percent-encoding."""
    track = tmp_path / "Sub Folder" / "01 - Track Name.flac"
    track.parent.mkdir(parents=True, exist_ok=True)
    track.write_bytes(b"fLaC")

    # Direct path
    assert parse_desktop_uri(str(track)) == track.resolve()

    # Percent-encoded file:// URI
    encoded_uri = f"file://{str(track.parent)}/01%20-%20Track%20Name.flac".replace(" ", "%20")
    assert parse_desktop_uri(encoded_uri) == track.resolve()


def test_parse_desktop_uri_rejects_remote_schemes() -> None:
    """Verify non-file schemes and remote hosts are rejected."""
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_desktop_uri("   ")

    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        parse_desktop_uri("https://example.com/malicious.flac")

    with pytest.raises(ValueError, match="Remote file URI host"):
        parse_desktop_uri("file://remote.host.local/share/track.flac")


def test_classify_mime_target_types(tmp_path: Path) -> None:
    """Verify audio, playlist, directory, and unsupported targets are classified accurately."""
    audio_file = tmp_path / "song.flac"
    audio_file.write_bytes(b"fLaC")
    playlist_file = tmp_path / "session.m3u8"
    playlist_file.write_text("#EXTM3U\nsong.flac\n", encoding="utf-8")
    other_file = tmp_path / "notes.txt"
    other_file.write_text("hello", encoding="utf-8")

    t_audio = classify_mime_target(str(audio_file))
    assert t_audio.target_type == "audio"
    assert t_audio.exists is True

    t_pl = classify_mime_target(playlist_file.as_uri())
    assert t_pl.target_type == "playlist"
    assert t_pl.exists is True

    t_dir = classify_mime_target(str(tmp_path))
    assert t_dir.target_type == "directory"
    assert t_dir.exists is True

    t_other = classify_mime_target(str(other_file))
    assert t_other.target_type == "unsupported"

    assert ".flac" in SUPPORTED_AUDIO_EXTENSIONS
    assert ".m3u8" in SUPPORTED_PLAYLIST_EXTENSIONS
    assert "audio/flac" in MIME_TYPE_ASSOCIATIONS


def test_parse_m3u_playlist(tmp_path: Path) -> None:
    """Verify M3U8 parsing resolves relative paths and file:// URIs while skipping comments."""
    track1 = (tmp_path / "track1.flac").resolve()
    track2 = (tmp_path / "sub" / "track2.mp3").resolve()
    track2.parent.mkdir(parents=True, exist_ok=True)
    track1.write_bytes(b"fLaC")
    track2.write_bytes(b"ID3")

    m3u8 = tmp_path / "mix.m3u8"
    m3u8.write_text(
        f"#EXTM3U\n#EXTINF:210,Artist - Track 1\ntrack1.flac\n#EXTINF:180,Artist - Track 2\n{track2.as_uri()}\nhttps://ignore.example/stream.mp3\n",
        encoding="utf-8",
    )

    parsed = parse_m3u_playlist(m3u8)
    assert parsed == [track1, track2]


def test_forward_uris_security_and_ipc(tmp_path: Path) -> None:
    """Verify forward_uris_to_running_instance enforces loopback host, 0o600 IPC state, and HTTP responses."""
    from vibeplay.desktop.mime import clear_ipc_state, read_ipc_state, write_ipc_state

    with pytest.raises(ValueError, match="loopback"):
        forward_uris_to_running_instance(["/tmp/a.flac"], host="0.0.0.0", port=8765)

    with pytest.raises(ValueError, match="loopback"):
        forward_uris_to_running_instance(["/tmp/a.flac"], host="127.evil.example", port=8765)

    assert forward_uris_to_running_instance([], host="127.0.0.1", port=8765) is False

    # Verify atomic 0o600 IPC state persistence and auto-discovery
    ipc_file = tmp_path / "desktop_ipc.json"
    write_ipc_state("127.0.0.1", 8910, "ephemeral_tok_abc", state_path=ipc_file)
    assert (ipc_file.stat().st_mode & 0o777) == 0o600
    loaded = read_ipc_state(ipc_file)
    assert loaded is not None
    assert loaded["token"] == "ephemeral_tok_abc"
    assert loaded["port"] == 8910

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    with patch("vibeplay.desktop.mime.urlopen", return_value=mock_resp) as mock_open:
        ok = forward_uris_to_running_instance(
            ["file:///tmp/test.flac"],
            host="::1",
            port=8765,
            token=None,
            ipc_state_path=ipc_file,
        )
        assert ok is True
        req = mock_open.call_args[0][0]
        assert req.full_url == "http://[::1]:8910/api/desktop/open"
        assert req.get_header("X-api-key") == "ephemeral_tok_abc"

    clear_ipc_state(ipc_file)
    assert not ipc_file.exists()


def test_desktop_main_forwards_to_running_instance() -> None:
    """Verify vibeplay-desktop %U forwards URIs and exits 0 if an instance is already running."""
    with (
        patch("vibeplay.desktop.mime.forward_uris_to_running_instance", return_value=True) as mock_fwd,
        patch("vibeplay.desktop.__main__.DesktopSupervisor") as mock_sup,
    ):
        rc = desktop_main(["--host", "127.0.0.1", "--port", "8765", "file:///tmp/song.flac"])
        assert rc == 0
        mock_fwd.assert_called_once_with(["file:///tmp/song.flac"], host="127.0.0.1", port=8765)
        mock_sup.assert_not_called()


def test_api_desktop_open_and_telemetry_stream(isolated_env) -> None:
    """Verify POST /api/desktop/open and GET /api/desktop/telemetry/stream endpoints."""
    db_path, _settings_path, music_dir, cfg = isolated_env
    track_path = (music_dir / "audiophile_demo.flac").resolve()
    track_path.write_bytes(b"fLaC")

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tracks (path, mtime, size, hash, title, artist, album, genre, duration, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                str(track_path),
                1700000000.0,
                4096,
                "hash_phase6_1",
                "Subterranean Pulse",
                "Klangwerk",
                "Deep Space",
                "Ambient",
                245.0,
            ),
        )
        conn.commit()

    app = create_app(db_path=db_path, settings=cfg)
    client = TestClient(app)

    with patch("vibeplay.web.play_track") as mock_play:
        resp = client.post(
            "/api/desktop/open",
            json={"uris": [track_path.as_uri()]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["played_track_id"] == 1
        assert data["opened"][0]["type"] == "audio"
        mock_play.assert_called_once_with(db_path.resolve(), 1, cfg)

    # Reject remote HTTP URI via /api/desktop/open
    bad_resp = client.post(
        "/api/desktop/open",
        json={"uris": ["http://evil.example.com/track.flac"]},
    )
    assert bad_resp.status_code == 400

    # Verify SSE telemetry stream endpoint
    with patch(
        "vibeplay.web.get_playback_status",
        side_effect=[
            {
                "track_id": 1,
                "title": "Subterranean Pulse",
                "artist": "Klangwerk",
                "sample_rate": "96000 Hz",
                "bit_depth": "24-bit",
                "daemon_online": True,
            },
            {
                "track_id": 2,
                "title": "Horizon Drift",
                "artist": "Klangwerk",
                "sample_rate": "192000 Hz",
                "bit_depth": "24-bit",
                "daemon_online": True,
            },
        ],
    ):
        sse1 = client.get("/api/desktop/telemetry/stream")
        assert sse1.status_code == 200
        assert "text/event-stream" in sse1.headers["content-type"]
        assert "event: telemetry_snapshot" in sse1.text
        assert '"sample_rate_hz": 96000' in sse1.text

        sse2 = client.get("/api/desktop/telemetry/stream")
        assert sse2.status_code == 200
        assert "event: track_transition" in sse2.text
        assert "event: dac_lock_changed" in sse2.text
        assert '"sample_rate_hz": 192000' in sse2.text
