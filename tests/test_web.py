"""Comprehensive route and integration tests for vibeplay FastAPI, HTMX, and Jinja2 web interface."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import (
    get_connection,
    init_db,
    insert_or_replace_features,
    insert_track,
)
from vibeplay.web import create_app


@pytest.fixture
def test_environment(tmp_path: Path) -> tuple[Path, Settings, TestClient]:
    """Create isolated SQLite database, test settings, and FastAPI TestClient."""
    db_file = tmp_path / "web_test.db"
    cache_dir = tmp_path / "vector_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        db_path=db_file,
        vector_cache_dir=cache_dir,
        weight_bpm=1.0,
        weight_loudness=0.5,
        weight_danceability=1.0,
        weight_energy=1.0,
        weight_mood=1.0,
        weight_embedding=0.8,
        bpm_harmonic_weight=0.8,
        pca_embedding_dimensions=4,
    )

    init_db(db_file)

    tracks_data = [
        # (id, title, artist, album, duration, bpm, key, scale, energy, dance, genre, happy, relaxed, acoustic)
        (
            1,
            "Summer Breeze",
            "Solaris",
            "Heatwave",
            200.0,
            120.0,
            "C",
            "major",
            0.3,
            0.4,
            "Ambient",
            0.8,
            0.9,
            0.2,
        ),
        (
            2,
            "Sunset Chill",
            "Solaris",
            "Heatwave",
            210.0,
            122.0,
            "G",
            "major",
            0.4,
            0.5,
            "Ambient",
            0.7,
            0.9,
            0.3,
        ),
        (
            3,
            "Overdrive",
            "Solaris",
            "Heatwave",
            180.0,
            128.0,
            "D",
            "major",
            0.5,
            0.6,
            "Rock",
            0.4,
            0.2,
            0.1,
        ),
        (
            4,
            "Nightfall",
            "Lunar",
            "Orbit",
            240.0,
            124.0,
            "A",
            "minor",
            0.6,
            0.7,
            "Electronic",
            0.3,
            0.4,
            0.1,
        ),
        (
            5,
            "Starlight",
            "Lunar",
            "Orbit",
            195.0,
            126.0,
            "E",
            "minor",
            0.7,
            0.8,
            "Electronic",
            0.4,
            0.3,
            0.1,
        ),
        (
            6,
            "Cosmic Pulse",
            "Apex",
            "Peak Time",
            220.0,
            130.0,
            "B",
            "minor",
            0.8,
            0.9,
            "Techno",
            0.2,
            0.1,
            0.0,
        ),
        (
            7,
            "Final Rush",
            "Apex",
            "Peak Time",
            210.0,
            132.0,
            "F#",
            "minor",
            0.9,
            0.85,
            "Techno",
            0.2,
            0.1,
            0.0,
        ),
        (
            8,
            "Acoustic Morning",
            "Echo Valley",
            "Roots",
            175.0,
            95.0,
            "C",
            "major",
            0.25,
            0.3,
            "Folk",
            0.7,
            0.8,
            0.95,
        ),
        (
            9,
            "Rustic Strings",
            "Echo Valley",
            "Roots",
            190.0,
            100.0,
            "G",
            "major",
            0.35,
            0.35,
            "Folk",
            0.6,
            0.8,
            0.90,
        ),
        (
            10,
            "Party Rock",
            "The Dynamos",
            "Groove",
            185.0,
            125.0,
            "F",
            "major",
            0.85,
            0.8,
            "Dance",
            0.95,
            0.1,
            0.1,
        ),
    ]

    with get_connection(db_file) as conn:
        for (
            tid,
            title,
            artist,
            album,
            dur,
            bpm,
            key,
            scale,
            energy,
            dance,
            genre,
            hap,
            rel,
            aco,
        ) in tracks_data:
            insert_track(
                conn,
                path=f"/music/{artist}/{album}/{title}.flac",
                mtime=1700000000.0 + tid,
                size=15000000,
                file_hash=f"hash_{tid}",
                duration=dur,
                bitrate=920000,
                title=title,
                artist=artist,
                album=album,
                track_no=tid,
                genre=genre,
            )
            moods = {
                "happy": hap,
                "sad": 0.1,
                "relaxed": rel,
                "aggressive": 0.8 if "Rush" in title or "Overdrive" in title else 0.1,
                "party": 0.95 if "Party" in title else 0.2,
                "acoustic": aco,
                "electronic": 0.9
                if "Techno" in genre or "Electronic" in genre
                else 0.1,
            }
            np.random.seed(tid)
            emb = np.random.randn(32).astype(np.float32).tobytes()
            insert_or_replace_features(
                conn,
                track_id=tid,
                analyzer_version="vibeplay-librosa-1.0",
                bpm=bpm,
                key=key,
                scale=scale,
                loudness=-8.0,
                danceability=dance,
                energy=energy,
                mood_scores_json=json.dumps(moods),
                embedding_blob=emb,
            )

    app = create_app(db_path=db_file, settings=settings)
    client = TestClient(app)
    return db_file, settings, client


def test_index_page(test_environment: tuple[Path, Settings, TestClient]) -> None:
    """Verify that root page renders dashboard telemetry, library table, and transport bar."""
    _, _, client = test_environment
    response = client.get("/")
    assert response.status_code == 200
    assert "vibeplay — Audiophile Precision Console" in response.text
    assert "Music Library" in response.text
    assert "Summer Breeze" in response.text
    assert "Solaris" in response.text
    assert "transport-footer" in response.text
    assert "Track Telemetry" not in response.text  # Modal starts empty/unopened


def test_library_table_filtering_and_sorting(
    test_environment: tuple[Path, Settings, TestClient],
) -> None:
    """Verify library table filtering by text, artist, Camelot key, mood, tempo, and sort."""
    _, _, client = test_environment

    # Baseline: all 10 tracks
    res_all = client.get("/api/library/table")
    assert res_all.status_code == 200
    assert "Summer Breeze" in res_all.text
    assert "Final Rush" in res_all.text
    assert "Showing 10 tracks" in res_all.text

    # Search filter 'q'
    res_q = client.get("/api/library/table?q=Rush")
    assert res_q.status_code == 200
    assert "Final Rush" in res_q.text
    assert "Summer Breeze" not in res_q.text

    # Artist filter
    res_art = client.get("/api/library/table?artist=Apex")
    assert res_art.status_code == 200
    assert "Cosmic Pulse" in res_art.text
    assert "Final Rush" in res_art.text
    assert "Summer Breeze" not in res_art.text

    # BPM range filter
    res_bpm = client.get("/api/library/table?bpm_min=90&bpm_max=105")
    assert res_bpm.status_code == 200
    assert "Acoustic Morning" in res_bpm.text
    assert "Rustic Strings" in res_bpm.text
    assert "Summer Breeze" not in res_bpm.text

    # Camelot harmonic key filter (C Major = 8B)
    res_key = client.get("/api/library/table?key=8B")
    assert res_key.status_code == 200
    assert "Summer Breeze" in res_key.text
    assert "Acoustic Morning" in res_key.text
    assert "Final Rush" not in res_key.text

    # Mood filter (acoustic >= 50%)
    res_mood = client.get("/api/library/table?mood=acoustic")
    assert res_mood.status_code == 200
    assert "Acoustic Morning" in res_mood.text
    assert "Rustic Strings" in res_mood.text
    assert "Cosmic Pulse" not in res_mood.text

    # Sort by BPM descending
    res_sort = client.get("/api/library/table?sort=bpm_desc")
    assert res_sort.status_code == 200
    # Final Rush (132 BPM) should appear before Acoustic Morning (95 BPM)
    idx_rush = res_sort.text.find("Final Rush")
    idx_folk = res_sort.text.find("Acoustic Morning")
    assert idx_rush != -1 and idx_folk != -1
    assert idx_rush < idx_folk


def test_track_detail_modal(
    test_environment: tuple[Path, Settings, TestClient],
) -> None:
    """Verify track detail partial renders audio specs and neural mood graphs."""
    _, _, client = test_environment

    # Valid track ID 1
    response = client.get("/api/track/1")
    assert response.status_code == 200
    assert "Summer Breeze" in response.text
    assert "Solaris" in response.text
    assert "Raw Hardware Audio Format Specs" in response.text
    assert "Sampling Rate" in response.text
    assert "Bit Depth" in response.text
    assert "Neural Mood Probabilities" in response.text
    assert "Happy" in response.text
    assert "Acoustic" in response.text

    # Non-existent track ID
    response_404 = client.get("/api/track/99999")
    assert response_404.status_code == 404


def test_cluster_cards_endpoint(
    test_environment: tuple[Path, Settings, TestClient],
) -> None:
    """Verify cluster cards HTMX partial computes and displays cluster centroids."""
    _, _, client = test_environment
    response = client.get("/api/clusters/cards")
    assert response.status_code == 200
    assert "cluster-card" in response.text
    assert "Build Cluster Playlist" in response.text


def test_playlist_generation_reorder_and_export(
    test_environment: tuple[Path, Settings, TestClient],
) -> None:
    """Verify playlist creation, drag-and-drop reordering, and M3U8 export."""
    _, _, client = test_environment

    # Generate smart playlist from seed track #1
    gen_res = client.post(
        "/api/playlist/generate",
        data={
            "name": "Precision Lounge Session",
            "seed_track_id": "1",
            "limit": "4",
            "energy": "0.40",
            "danceability": "0.50",
            "max_artist_tracks": "2",
        },
    )
    assert gen_res.status_code == 200
    assert "Precision Lounge Session" in gen_res.text
    assert "playlist-track-row" in gen_res.text
    assert "Export M3U8" in gen_res.text
    assert "Play in MPD" in gen_res.text

    # Parse playlist_id from data-playlist-id attribute
    match = re.search(r'data-playlist-id="(\d+)"', gen_res.text)
    assert match is not None
    playlist_id = int(match.group(1))

    # Parse initial track IDs
    track_matches = re.findall(r'data-track-id="(\d+)"', gen_res.text)
    assert len(track_matches) >= 2
    initial_ids = [int(x) for x in track_matches]

    # Export M3U8 file
    export_res = client.get(f"/api/playlist/{playlist_id}/export-m3u8")
    assert export_res.status_code == 200
    assert export_res.headers["content-type"].startswith("audio/x-mpegurl")
    assert "#EXTM3U" in export_res.text
    assert "#EXTINF:" in export_res.text
    assert f"_{playlist_id}.m3u8" in export_res.headers["content-disposition"]

    # Reorder tracks (reverse initial order)
    reversed_ids = list(reversed(initial_ids))
    reorder_res = client.post(
        "/api/playlist/reorder",
        data={
            "playlist_id": str(playlist_id),
            "track_ids": ",".join(str(x) for x in reversed_ids),
        },
    )
    assert reorder_res.status_code == 200
    new_track_matches = [
        int(x) for x in re.findall(r'data-track-id="(\d+)"', reorder_res.text)
    ]
    assert new_track_matches == reversed_ids

    # Reorder validation errors
    bad_req = client.post(
        "/api/playlist/reorder",
        data={"playlist_id": str(playlist_id), "track_ids": "not_an_id"},
    )
    assert bad_req.status_code == 400

    not_found = client.post(
        "/api/playlist/reorder", data={"playlist_id": "99999", "track_ids": "1,2"}
    )
    assert not_found.status_code == 404


def test_player_controls_and_telemetry(
    test_environment: tuple[Path, Settings, TestClient],
) -> None:
    """Verify hardware DAC telemetry status JSON and all player control endpoints."""
    _, _, client = test_environment

    # Status JSON telemetry polling endpoint
    status_res = client.get("/api/player/status")
    assert status_res.status_code == 200
    st_data = status_res.json()
    assert "sample_rate" in st_data
    assert "bit_depth" in st_data
    assert "buffer_health" in st_data
    assert "state" in st_data
    assert "output_profile" in st_data
    assert st_data["bit_perfect"] is True

    # Transport HTML bar polling endpoint
    transport_res = client.get("/api/player/transport")
    assert transport_res.status_code == 200
    assert "transport-footer" in transport_res.text
    assert "scrub-bar" in transport_res.text

    # Toggle playback
    toggle_res = client.post("/api/player/toggle")
    assert toggle_res.status_code == 200
    assert "transport-footer" in toggle_res.text

    # Next / Prev
    assert client.post("/api/player/next").status_code == 200
    assert client.post("/api/player/prev").status_code == 200

    # Volume change
    vol_res = client.post("/api/player/volume", data={"volume": "75"})
    assert vol_res.status_code == 200

    # Volume step adjustments (e.g. F5 / F7 keybindings)
    step_res = client.post("/api/player/volume-step", data={"delta": "5"})
    assert step_res.status_code == 200
    assert "transport-footer" in step_res.text

    step_down = client.post("/api/player/volume-step", data={"delta": "-5"})
    assert step_down.status_code == 200
    assert "transport-footer" in step_down.text

    # Mute toggle (e.g. F6 keybinding)
    mute_res = client.post("/api/player/mute-toggle")
    assert mute_res.status_code == 200
    assert "transport-footer" in mute_res.text

    # Output profile switch
    out_res = client.post("/api/player/output", data={"profile": "Headphones"})
    assert out_res.status_code == 200
    assert "Headphones" in out_res.text

    # Direct play track
    play_tr_res = client.post("/api/player/play-track/1")
    assert play_tr_res.status_code == 200
    assert "transport-footer" in play_tr_res.text


def test_api_authentication_middleware(test_environment: tuple[Path, Settings, TestClient]) -> None:
    """Verify API authentication enforcement, token headers, and 401 rejections."""
    db_file, cfg, _ = test_environment
    from fastapi.testclient import TestClient
    from vibeplay.web import create_app

    auth_app = create_app(db_path=db_file, settings=cfg, api_key="secret-key-12345")
    auth_client = TestClient(auth_app)

    # 1. Unauthenticated request rejected with 401
    unauth_api = auth_client.get("/api/player/status")
    assert unauth_api.status_code == 401
    assert "Unauthorized" in unauth_api.text

    unauth_html = auth_client.get("/", headers={"accept": "text/html"})
    assert unauth_html.status_code == 401
    assert "401 Unauthorized" in unauth_html.text

    # 2. X-API-Key header accepted
    header_res = auth_client.get("/api/player/status", headers={"X-API-Key": "secret-key-12345"})
    assert header_res.status_code == 200

    # 3. Authorization Bearer header accepted
    bearer_res = auth_client.get("/api/player/status", headers={"Authorization": "Bearer secret-key-12345"})
    assert bearer_res.status_code == 200

    # 4. Query parameter accepted and sets cookie
    query_res = auth_client.get("/?api_key=secret-key-12345")
    assert query_res.status_code == 200
    assert "vibeplay_api_key" in query_res.cookies


def test_localhost_server_guardrails(tmp_path: Path) -> None:
    """Verify run_server blocks unauthenticated remote interface binding."""
    from vibeplay.web import run_server

    db_file = tmp_path / "test.db"

    # Attempting to bind 0.0.0.0 without auth or override raises ValueError
    with pytest.raises(ValueError, match="Security Guardrail"):
        run_server(db_path=db_file, host="0.0.0.0", port=8000)

    # With allow_insecure_remote, it proceeds to uvicorn.run
    with patch("uvicorn.run") as mock_uvicorn:
        run_server(db_path=db_file, host="0.0.0.0", port=8000, allow_insecure_remote=True)
        mock_uvicorn.assert_called_once()

    # With API key configured, it proceeds to uvicorn.run
    with patch("uvicorn.run") as mock_uvicorn:
        run_server(db_path=db_file, host="0.0.0.0", port=8000, api_key="secret")
        mock_uvicorn.assert_called_once()


def test_operational_health_in_status_endpoint(test_environment: tuple[Path, Settings, TestClient]) -> None:
    """Verify operational health diagnostics in /api/player/status."""
    _, _, client = test_environment

    res = client.get("/api/player/status")
    assert res.status_code == 200
    data = res.json()
    assert "services" in data
    assert "mpd" in data["services"]
    assert "database" in data["services"]
    assert "acoustid" in data["services"]
    assert "llm" in data["services"]
    assert data["services"]["database"] == "connected"

