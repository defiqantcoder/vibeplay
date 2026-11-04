import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from vibeplay.web import create_app
from vibeplay.db import init_db
import contextlib

@pytest.fixture
def test_client(tmp_path):
    db_file = tmp_path / "test_db.sqlite"
    init_db(db_file)
    app = create_app(db_path=db_file)
    return TestClient(app)

def test_headless_ui_controls(test_client, mocker):
    mocker.patch("vibeplay.player.toggle_pause")
    mocker.patch("vibeplay.player.next_song")
    mocker.patch("vibeplay.player.previous_song")
    mocker.patch("vibeplay.player.set_volume_level")
    mocker.patch("vibeplay.player.adjust_volume_step")
    mocker.patch("vibeplay.player.toggle_mute")

    resp = test_client.post("/api/player/toggle")
    assert resp.status_code in (200, 303)

    resp = test_client.post("/api/player/next")
    assert resp.status_code in (200, 303)

    resp = test_client.post("/api/player/prev")
    assert resp.status_code in (200, 303)

    resp = test_client.post("/api/player/volume-step?delta=5")
    assert resp.status_code in (200, 303)

    resp = test_client.post("/api/player/mute-toggle")
    assert resp.status_code in (200, 303)
