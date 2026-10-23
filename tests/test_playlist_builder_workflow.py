import pytest
from fastapi.testclient import TestClient
from bs4 import BeautifulSoup
from pathlib import Path

from vibeplay.web import create_app
from vibeplay.config import Settings


@pytest.fixture
def test_client(seed_test_database, tmp_path):
    db_file = tmp_path / "test_vibeplay.db"
    seed_track_ids = seed_test_database(db_file)

    cfg = Settings(
        music_dir=str(tmp_path),
        db_path=str(db_file),
    )

    app = create_app(settings=cfg)
    client = TestClient(app)
    return client, seed_track_ids, db_file


def test_playlist_builder_render(test_client):
    client, _, _ = test_client
    pass


def test_playlist_preview_generation(test_client):
    client, seed_track_ids, _ = test_client
    seed_id = seed_track_ids[0]

    response = client.post("/api/playlist/generate", data={"seed_track_id": str(seed_id), "arc": "ramp_up", "limit": 5, "max_bpm_delta": 5.0})

    assert response.status_code == 200
    html = response.text
    assert "builder-tracks-container" in html
    assert "Drag and drop tracks to reorder playlist sequence" in html
    assert "Harmonic Match:" in html
    assert "Energy Step:" in html


def test_harmonic_transition_calculation(test_client):
    client, seed_track_ids, _ = test_client
    seed_id = seed_track_ids[0]

    response = client.post(
        "/api/playlist/generate",
        data={
            "seed_track_id": str(seed_id),
            "limit": 3,
        },
    )
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, "html.parser")
    list_div = soup.find("div", id="playlist-tracks-list")
    assert list_div is not None

    playlist_id = list_div["data-playlist-id"]

    track_rows = list_div.find_all("div", class_="playlist-track-row")
    track_ids = [row["data-track-id"] for row in track_rows]

    assert len(track_ids) > 0

    reversed_track_ids = list(reversed(track_ids))

    reorder_response = client.post("/api/playlist/reorder", data={"playlist_id": playlist_id, "track_ids": ",".join(reversed_track_ids)})

    assert reorder_response.status_code == 200

    new_soup = BeautifulSoup(reorder_response.text, "html.parser")
    new_list_div = new_soup.find("div", id="playlist-tracks-list")
    new_track_rows = new_list_div.find_all("div", class_="playlist-track-row")

    new_track_ids_ordered = [row["data-track-id"] for row in new_track_rows]
    assert new_track_ids_ordered == reversed_track_ids

    html = reorder_response.text
    assert "Harmonic Match:" in html
    assert "Energy Step:" in html
