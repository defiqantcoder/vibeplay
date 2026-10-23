import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db, insert_track
from vibeplay.player import get_audio_file_technical_info
from vibeplay.web import create_app


def test_get_audio_file_technical_info_caching(tmp_path: Path):
    """Verify that get_audio_file_technical_info caches results."""
    # Create a dummy audio file
    dummy_file = tmp_path / "test.flac"
    dummy_file.touch()

    # Clear cache before test
    get_audio_file_technical_info.cache_clear()

    # First call - should be a miss
    info1 = get_audio_file_technical_info(str(dummy_file))

    # Second call - should be a hit
    info2 = get_audio_file_technical_info(str(dummy_file))

    assert info1 == info2

    # Check cache info
    cache_info = get_audio_file_technical_info.cache_info()
    assert cache_info.hits >= 1


@pytest.fixture
def local_test_env(tmp_path: Path) -> tuple[Path, Settings, TestClient]:
    db_file = tmp_path / "test_perf.db"
    init_db(db_file)
    with get_connection(db_file) as conn:
        insert_track(
            conn,
            path=str(tmp_path / "music" / "song.flac"),
            mtime=1700000000.0,
            size=10000000,
            file_hash="ph1",
            duration=180.0,
            title="Summer Breeze",
            artist="Artist A",
            album="Album One",
        )
        conn.execute(
            "INSERT INTO features (track_id, analyzer_version, key, scale, mood_scores) VALUES (1, '1.0', 'C', 'major', ?)",
            (json.dumps({"happy": 0.8, "acoustic": 0.9, "electronic": 0.1}),),
        )
        conn.commit()

    cfg = Settings(api_key="test-key")
    app = create_app(db_path=db_file, settings=cfg, api_key="test-key")
    client = TestClient(app)
    # inject api key
    client.cookies.set("vibeplay_api_key", "test-key")
    return db_file, cfg, client


def test_track_inspector_endpoint(local_test_env: tuple[Path, Settings, TestClient]):
    db_file, cfg, client = local_test_env

    # Request the inspector endpoint
    response = client.get("/api/track/1/inspector")

    assert response.status_code == 200
    html = response.text

    # Verify expected elements
    assert "track-inspector-panel" in html
    assert "⚡ Set as Vibe Seed" in html
    assert "Acoustic Properties" in html

    # Verify track details from DB
    assert "Summer Breeze" in html  # from test_environment setup
    assert "C" in html
    assert "major" in html

    # Verify tech info presence
    assert "FLAC" in html or "Free Lossless Audio Codec" in html or "MPEG Audio Layer 3" in html or "Audio" in html  # Depending on dummy fallback

    # Verify mood properties
    assert "happy" in html.lower()
    assert "acoustic" in html.lower()

    # 404 check
    res_404 = client.get("/api/track/9999/inspector")
    assert res_404.status_code == 404
