import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import delete_saved_playlist, get_connection, get_saved_playlists, migrate_db, save_playlist
from vibeplay.web import create_app


@pytest.fixture
def playlist_settings(tmp_path: Path):
    db_file = tmp_path / "test_saved_playlists.db"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        db_path=db_file,
        acoustid_api_key="test_key",
        cache_dir=cache_dir,
        desktop_settings_path=tmp_path / "desktop_settings.json",
    )

@pytest.fixture
def test_client(playlist_settings: Settings, tmp_path: Path):
    os.environ["VIBEPLAY_DB_PATH"] = str(playlist_settings.db_path)
    os.environ["VIBEPLAY_CONFIG_PATH"] = str(tmp_path / "config.json")

    # create the db so that web can use it
    with get_connection(playlist_settings.db_path) as conn:
        migrate_db(conn)

    settings_file = tmp_path / "desktop_settings.json"
    settings_file.write_text("{}", encoding="utf-8")

    with patch("vibeplay.desktop.settings.DEFAULT_DESKTOP_SETTINGS_PATH", settings_file):
        app = create_app(settings=playlist_settings)
        return TestClient(app)

def test_db_saved_playlists_crud(playlist_settings: Settings):
    db_path = playlist_settings.db_path

    with get_connection(db_path) as conn:
        migrate_db(conn)
        conn.execute("INSERT INTO tracks (id, path, mtime, size, hash, duration, status) VALUES (1, 't1.flac', 0, 0, 'h1', 100, 'active')")
        conn.execute("INSERT INTO tracks (id, path, mtime, size, hash, duration, status) VALUES (2, 't2.flac', 0, 0, 'h2', 200, 'active')")

        pl_id = save_playlist(conn, "My Lounge", "chill", [1, 2])
        assert pl_id > 0

        playlists = get_saved_playlists(conn)
        assert len(playlists) == 1
        assert playlists[0]["name"] == "My Lounge"
        assert playlists[0]["vibe_arc"] == "chill"
        assert playlists[0]["track_count"] == 2
        assert playlists[0]["total_duration"] == 300.0

        assert delete_saved_playlist(conn, pl_id) is True
        playlists_after = get_saved_playlists(conn)
        assert len(playlists_after) == 0

def test_api_save_playlist(test_client, playlist_settings: Settings):
    db_path = playlist_settings.db_path

    with get_connection(db_path) as conn:
        conn.execute("INSERT INTO tracks (id, path, mtime, size, hash, duration, status) VALUES (1, 't1.flac', 0, 0, 'h1', 100, 'active')")

    response = test_client.post("/api/playlist/save", data={
        "name": "API Playlist",
        "vibe_arc": "energy_ramp",
        "track_ids_json": "[1]"
    })

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert "playlist_id" in response.json()

    pl_id = response.json()["playlist_id"]
    with get_connection(db_path) as conn:
        playlists = get_saved_playlists(conn)
        assert len(playlists) >= 1
        found = next(p for p in playlists if p["id"] == pl_id)
        assert found["name"] == "API Playlist"

def test_api_export_m3u8(test_client, playlist_settings: Settings):
    db_path = playlist_settings.db_path
    with get_connection(db_path) as conn:
        conn.execute("INSERT INTO tracks (id, path, mtime, size, hash, duration, status, artist, title) VALUES (10, 'my/track.flac', 0, 0, 'h1', 120, 'active', 'TestArtist', 'TestTitle')")
        pl_id = save_playlist(conn, "Export Playlist", "chill", [10])

    response = test_client.get(f"/api/playlist/{pl_id}/export")
    assert response.status_code == 200
    assert "audio/x-mpegurl" in response.headers["content-type"]
    assert "Export_Playlist" in response.headers["content-disposition"]

    content = response.text
    assert content.startswith("#EXTM3U")
    assert "#EXTINF:120,TestArtist - TestTitle" in content
    assert "my/track.flac" in content

def test_api_import_m3u8(test_client, playlist_settings: Settings, tmp_path):
    db_path = playlist_settings.db_path
    with get_connection(db_path) as conn:
        conn.execute("INSERT INTO tracks (id, path, mtime, size, hash, duration, status) VALUES (20, 'import/target.flac', 0, 0, 'h1', 100, 'active')")

    m3u8_content = "#EXTM3U\n#EXTINF:100,Unknown - Unknown\nimport/target.flac\n"
    test_file = tmp_path / "test_import.m3u8"
    test_file.write_text(m3u8_content)

    with open(test_file, "rb") as f:
        response = test_client.post("/api/playlist/import", files={"file": ("test_import.m3u8", f, "audio/x-mpegurl")})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["matched_tracks"] == 1

    pl_id = response.json()["playlist_id"]
    with get_connection(db_path) as conn:
        playlists = get_saved_playlists(conn)
        found = next((p for p in playlists if p["id"] == pl_id), None)
        assert found is not None
        assert found["name"] == "test_import"
        assert found["track_count"] == 1

def test_api_delete_playlist(test_client, playlist_settings: Settings):
    db_path = playlist_settings.db_path
    with get_connection(db_path) as conn:
        pl_id = save_playlist(conn, "Delete Me", "chill", [])

    response = test_client.delete(f"/api/playlist/{pl_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    with get_connection(db_path) as conn:
        playlists = get_saved_playlists(conn)
        assert not any(p["id"] == pl_id for p in playlists)
