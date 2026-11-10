from types import SimpleNamespace

import mutagen
import pytest
from fastapi.testclient import TestClient
from mutagen.flac import FLAC
from mutagen.mp4 import MP4Cover, MP4Tags

from vibeplay.api.library import extract_cover_bytes
from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db, insert_track
from vibeplay.web import create_app


def test_non_existent_file_returns_none(tmp_path):
    assert extract_cover_bytes(tmp_path / "non_existent.flac") is None


def test_zero_byte_file_returns_none(tmp_path):
    mock_file = tmp_path / "zero_byte.flac"
    mock_file.touch()
    assert extract_cover_bytes(mock_file) is None


def test_folder_image_returned(tmp_path):
    mock_audio = tmp_path / "song.flac"
    mock_audio.touch()
    mock_cover = tmp_path / "cover.jpg"
    mock_cover.write_bytes(b"dummy_jpeg_data")

    result = extract_cover_bytes(mock_audio)
    assert result is not None
    assert result[0] == b"dummy_jpeg_data"
    assert result[1] == "image/jpeg"


def test_flac_covr_text_comment_returns_folder_art(tmp_path):
    audio_path = tmp_path / "song.flac"
    # Minimal FLAC STREAMINFO: 44.1 kHz, stereo, 16 bits, no audio frames.
    stream_info = b"\x00\x10\x00\x10" + b"\x00" * 6 + ((44100 << 44) | (1 << 41) | (15 << 36)).to_bytes(8, "big") + b"\x00" * 16
    audio_path.write_bytes(b"fLaC\x80\x00\x00\x22" + stream_info)
    cover_data = b"folder_jpeg_data"
    (tmp_path / "cover.jpg").write_bytes(cover_data)

    audio = FLAC(audio_path)
    audio.add_tags()
    audio.tags["COVR"] = ["This is a text comment, not artwork"]
    audio.save()

    db_path = tmp_path / "library.db"
    init_db(db_path)
    with get_connection(db_path) as conn:
        track_id = insert_track(conn, path=str(audio_path), mtime=0, size=0, file_hash="flac-with-covr")
    settings = Settings(db_path=db_path, music_directory=tmp_path, desktop_settings_path=tmp_path / "settings.json")
    app = create_app(db_path=db_path, settings=settings, api_key="test-token")
    with TestClient(app) as client:
        response = client.get(f"/api/library/cover/{track_id}", headers={"X-API-Key": "test-token"})

    assert response.status_code == 200
    assert response.content == cover_data
    assert response.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize("data, mime", [(b"jpeg_artwork", "image/jpeg"), (b"\x89PNG_artwork", "image/png")])
def test_mp4_embedded_cover_returned(tmp_path, monkeypatch, data, mime):
    audio_path = tmp_path / "song.m4a"
    audio_path.touch()
    (tmp_path / "cover.jpg").write_bytes(b"folder_artwork")
    audio = SimpleNamespace(tags=MP4Tags())
    audio.tags["covr"] = [MP4Cover(data)]
    monkeypatch.setattr(mutagen, "File", lambda path: audio)

    assert extract_cover_bytes(audio_path) == (data, mime)
