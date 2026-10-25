"""Tests for desktop shortcut latency and optimistic playback controls."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.web import create_app


@pytest.fixture
def test_client(tmp_path: Path):
    settings_file = tmp_path / "desktop_settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    with patch("vibeplay.desktop.settings.DEFAULT_DESKTOP_SETTINGS_PATH", settings_file):
        settings = Settings(
            db_path=tmp_path / "test_shortcuts.db",
            config_path=tmp_path / "test_shortcuts.json",
            desktop_settings_path=settings_file,
            mpd_host="127.0.0.1",
            mpd_port=6600,
        )
        app = create_app(db_path=tmp_path / "test_shortcuts.db", settings=settings)
        return TestClient(app)


def test_api_player_toggle_latency(test_client: TestClient) -> None:
    """Ensure the /api/player/toggle endpoint returns in <50ms without blocking on MPD."""
    with patch("vibeplay.web.toggle_pause") as mock_toggle, patch("vibeplay.web.get_playback_status") as mock_status:

        def slow_toggle(*args, **kwargs):
            time.sleep(0.3)  # Simulate slow MPD connection

        mock_toggle.side_effect = slow_toggle
        mock_status.return_value = {"state": "stop", "volume": 50, "output_profiles": []}

        start_time = time.time()
        response = test_client.post("/api/player/toggle")
        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 0.100  # Non-blocking, returns well under 100ms
        assert "transport-bar" in response.text or "btn-play-pause" in response.text


def test_api_player_next_latency(test_client: TestClient) -> None:
    """Ensure the /api/player/next endpoint returns in <50ms without blocking on MPD."""
    with patch("vibeplay.web.next_song") as mock_next, patch("vibeplay.web.get_playback_status") as mock_status:

        def slow_next(*args, **kwargs):
            time.sleep(0.3)

        mock_next.side_effect = slow_next
        mock_status.return_value = {"state": "play", "volume": 50, "output_profiles": []}

        start_time = time.time()
        response = test_client.post("/api/player/next")
        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 0.100


def test_api_player_prev_latency(test_client: TestClient) -> None:
    """Ensure the /api/player/prev endpoint returns in <50ms without blocking on MPD."""
    with patch("vibeplay.web.previous_song") as mock_prev, patch("vibeplay.web.get_playback_status") as mock_status:

        def slow_prev(*args, **kwargs):
            time.sleep(0.3)

        mock_prev.side_effect = slow_prev
        mock_status.return_value = {"state": "play", "volume": 50, "output_profiles": []}

        start_time = time.time()
        response = test_client.post("/api/player/prev")
        elapsed = time.time() - start_time

        assert response.status_code == 200
        assert elapsed < 0.100
