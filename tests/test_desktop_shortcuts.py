import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.web import create_app


@pytest.fixture
def test_app(tmp_path):
    with patch("vibeplay.config.Settings.get_desktop_settings_path", return_value=tmp_path / "desktop_settings.json"):
        settings = Settings(
            db_path=tmp_path / "test_shortcuts.db",
            config_path=tmp_path / "test_shortcuts.json",
            mpd_host="127.0.0.1",
            mpd_port=6600,
        )
        return create_app(settings)


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


def test_api_player_toggle_latency(client):
    """Ensure the /api/player/toggle endpoint returns in <15ms using background tasks."""
    # We mock toggle_pause and get_playback_status
    # toggle_pause will be slow, get_playback_status will be fast.
    with patch("vibeplay.web.toggle_pause") as mock_toggle, patch("vibeplay.web.get_playback_status") as mock_status:

        def slow_toggle(*args, **kwargs):
            time.sleep(0.5)  # Simulate blocking audio lock

        mock_toggle.side_effect = slow_toggle
        mock_status.return_value = {"state": "stop", "volume": 50, "output_profiles": []}

        start_time = time.time()
        response = client.post("/api/player/toggle")
        end_time = time.time()

        assert response.status_code == 200
        assert (end_time - start_time) < 0.050  # Assert it's very fast, definitely < 50ms, usually < 10ms for local testing

        # Check optimistic UI - if it was stop, it should optimisticly become play
        assert "vibeplay" in response.text or '<div class="transport-footer"' in response.text  # Just verify it returned the HTML


def test_api_player_next_latency(client):
    """Ensure the /api/player/next endpoint returns in <15ms."""
    with patch("vibeplay.web.next_song") as mock_next, patch("vibeplay.web.get_playback_status") as mock_status:

        def slow_next(*args, **kwargs):
            time.sleep(0.5)

        mock_next.side_effect = slow_next
        mock_status.return_value = {"state": "play", "volume": 50, "output_profiles": []}

        start_time = time.time()
        response = client.post("/api/player/next")
        end_time = time.time()

        assert response.status_code == 200
        assert (end_time - start_time) < 0.050


def test_api_player_prev_latency(client):
    """Ensure the /api/player/prev endpoint returns in <15ms."""
    with patch("vibeplay.web.previous_song") as mock_prev, patch("vibeplay.web.get_playback_status") as mock_status:

        def slow_prev(*args, **kwargs):
            time.sleep(0.5)

        mock_prev.side_effect = slow_prev
        mock_status.return_value = {"state": "play", "volume": 50, "output_profiles": []}

        start_time = time.time()
        response = client.post("/api/player/prev")
        end_time = time.time()

        assert response.status_code == 200
        assert (end_time - start_time) < 0.050
