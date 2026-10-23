"""Comprehensive tests for Item 1: Guided Playlist Builder with Drag-and-Drop and Harmonic Transition Scoring."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import (
    get_connection,
    get_playlist,
    get_playlist_tracks,
    init_db,
    insert_or_replace_features,
    insert_track,
)
from vibeplay.playlist import (
    PlaylistRuleConfig,
    PlaylistTrackItem,
    calculate_playlist_summary,
    calculate_transition,
    calculate_transition_metrics,
    evaluate_energy_arc,
    evaluate_harmonic_transition,
    generate_playlist,
    key_to_camelot,
)
from vibeplay.web import create_app


@pytest.fixture
def test_env(tmp_path: Path):
    """Fixture providing isolated SQLite database, settings, and TestClient."""
    db_file = tmp_path / "test_builder.db"
    settings_file = tmp_path / "desktop_settings.json"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    init_db(db_file)
    cfg = Settings(
        db_path=db_file,
        desktop_settings_path=settings_file,
        vector_cache_dir=cache_dir,
    )

    track_metas = [
        # (id, title, artist, album, duration, bpm, key, scale, energy, danceability, genre)
        (1, "Deep Awakening", "Aura", "Genesis", 240.0, 120.0, "A", "minor", 0.35, 0.50, "Ambient"),      # 8A
        (2, "Celestial Drift", "Aura", "Genesis", 210.0, 120.5, "C", "major", 0.45, 0.55, "Ambient"),      # 8B (relative)
        (3, "Solar Flare", "Sol", "Equinox", 200.0, 122.0, "E", "minor", 0.65, 0.70, "House"),            # 9A (+1 boost)
        (4, "Prism Wave", "Sol", "Equinox", 225.0, 123.0, "B", "minor", 0.75, 0.75, "House"),             # 10A (+2 shift)
        (5, "Subatomic", "Pulse", "Quantum", 195.0, 126.0, "G", "minor", 0.85, 0.80, "Techno"),           # 6A (clash -2)
        (6, "Apex Velocity", "Pulse", "Quantum", 215.0, 128.0, "D", "minor", 0.90, 0.85, "Techno"),        # 7A (-1 drop)
        (7, "Cosmic Horizon", "Nova", "Starlight", 250.0, 130.0, "D#", "minor", 0.80, 0.70, "Trance"),     # 2A (opposite 8A)
        (8, "Nocturne Echo", "Nova", "Starlight", 180.0, 100.0, "A", "minor", 0.25, 0.40, "Downtempo"),    # 8A tempo drop
    ]

    with get_connection(db_file) as conn:
        for tid, title, artist, album, dur, bpm, key, scale, energy, dance, genre in track_metas:
            insert_track(
                conn,
                path=f"/music/{artist}/{album}/{title}.flac",
                mtime=1700000000.0 + tid,
                size=12000000,
                file_hash=f"hash_builder_{tid}",
                duration=dur,
                bitrate=921600,
                title=title,
                artist=artist,
                album=album,
                track_no=tid,
                genre=genre,
            )
            moods = {
                "happy": 0.7 if "Solar" in title or "Wave" in title else 0.3,
                "sad": 0.2,
                "relaxed": 0.8 if "Awakening" in title or "Nocturne" in title else 0.2,
                "aggressive": 0.8 if "Velocity" in title or "Subatomic" in title else 0.1,
                "party": 0.8 if genre in ("House", "Techno") else 0.2,
                "acoustic": 0.1,
                "electronic": 0.9 if genre in ("House", "Techno", "Trance") else 0.3,
            }
            emb = np.sin(np.linspace(0.1 * tid, tid, 128)).astype(np.float32)
            insert_or_replace_features(
                conn,
                track_id=tid,
                analyzer_version="1.0.0",
                bpm=bpm,
                key=key,
                scale=scale,
                loudness=-12.0 + energy * 6.0,
                danceability=dance,
                energy=energy,
                mood_scores_json=json.dumps(moods),
                embedding_blob=emb.tobytes(),
            )

    app = create_app(db_path=db_file, settings=cfg)
    client = TestClient(app)
    return db_file, settings_file, cfg, client


def test_evaluate_harmonic_transition_exact_and_relative():
    """Verify exact matches and relative major/minor matches evaluate to seamless transitions."""
    # Exact Match: 8A -> 8A
    res1 = evaluate_harmonic_transition(from_camelot="8A", to_camelot="8A", from_bpm=120.0, to_bpm=120.0)
    assert res1["harmonic_type"] == "exact"
    assert res1["harmonic_badge"] == "seamless"
    assert res1["quality"] == "Seamless"
    assert res1["relation_label"] == "8A -> 8A [Exact Harmonic Match]"
    assert res1["harmonic_score"] == 100.0
    assert res1["total_score"] == 100.0
    assert res1["clash_level"] == 0

    # Exact Match: 8B -> 8B
    res2 = evaluate_harmonic_transition(from_camelot="8B", to_camelot="8B", from_bpm=124.0, to_bpm=124.0)
    assert res2["harmonic_type"] == "exact"
    assert res2["harmonic_badge"] == "seamless"
    assert res2["relation_label"] == "8B -> 8B [Exact Harmonic Match]"

    # Relative Major/Minor: 8A -> 8B
    res3 = evaluate_harmonic_transition(from_camelot="8A", to_camelot="8B", from_bpm=120.0, to_bpm=120.0)
    assert res3["harmonic_type"] == "relative"
    assert res3["harmonic_badge"] == "seamless"
    assert res3["quality"] == "Seamless"
    assert res3["relation_label"] == "8A -> 8B [Exact Harmonic Match]"
    assert res3["harmonic_score"] == 95.0
    assert res3["clash_level"] == 0

    # Relative Major/Minor: 8B -> 8A
    res4 = evaluate_harmonic_transition(from_camelot="8B", to_camelot="8A", from_bpm=128.0, to_bpm=128.0)
    assert res4["harmonic_type"] == "relative"
    assert res4["harmonic_badge"] == "seamless"
    assert res4["relation_label"] == "8B -> 8A [Exact Harmonic Match]"


def test_evaluate_harmonic_transition_energy_boost_and_drop():
    """Verify +1 energy boosts, -1 drops, and circular wrap-around transitions."""
    # +1 Energy Boost: 8A -> 9A
    res_boost = evaluate_harmonic_transition(from_camelot="8A", to_camelot="9A", from_bpm=120.0, to_bpm=122.0)
    assert res_boost["harmonic_type"] == "boost"
    assert res_boost["harmonic_badge"] == "harmonic-boost"
    assert res_boost["relation_label"] == "8A -> 9A [+1 Energy Boost]"
    assert res_boost["harmonic_score"] == 90.0
    assert res_boost["clash_level"] == 0

    # +1 Energy Boost wrap-around: 12A -> 1A
    res_wrap_boost = evaluate_harmonic_transition(from_camelot="12A", to_camelot="1A", from_bpm=125.0, to_bpm=125.0)
    assert res_wrap_boost["harmonic_type"] == "boost"
    assert res_wrap_boost["relation_label"] == "12A -> 1A [+1 Energy Boost]"

    # -1 Energy Drop: 8A -> 7A
    res_drop = evaluate_harmonic_transition(from_camelot="8A", to_camelot="7A", from_bpm=120.0, to_bpm=119.0)
    assert res_drop["harmonic_type"] == "drop"
    assert res_drop["harmonic_badge"] == "acceptable"
    assert res_drop["relation_label"] == "8A -> 7A [-1 Energy Drop]"
    assert res_drop["harmonic_score"] == 85.0

    # -1 Energy Drop wrap-around: 1A -> 12A
    res_wrap_drop = evaluate_harmonic_transition(from_camelot="1A", to_camelot="12A", from_bpm=120.0, to_bpm=120.0)
    assert res_wrap_drop["harmonic_type"] == "drop"
    assert res_wrap_drop["relation_label"] == "1A -> 12A [-1 Energy Drop]"

    # Diagonal mode shift: 8A -> 9B
    res_diag = evaluate_harmonic_transition(from_camelot="8A", to_camelot="9B", from_bpm=120.0, to_bpm=120.0)
    assert res_diag["harmonic_type"] == "pivot"
    assert res_diag["harmonic_badge"] == "acceptable"
    assert "Diagonal Mode Shift" in res_diag["relation_label"]


def test_evaluate_harmonic_transition_clashes_and_dissonance():
    """Verify harmonic clashes produce clear warning labels and color badges."""
    # Backward jump of 2: 8A -> 6A
    res_clash2 = evaluate_harmonic_transition(from_camelot="8A", to_camelot="6A", from_bpm=120.0, to_bpm=126.0)
    assert res_clash2["harmonic_type"] == "clash"
    assert res_clash2["harmonic_badge"] == "clash"
    assert res_clash2["relation_label"] == "8A -> 6A [Harmonic Clash -2]"
    assert res_clash2["clash_level"] == 2

    # Opposite side of wheel: 8A -> 2A (+6 steps)
    res_clash6 = evaluate_harmonic_transition(from_camelot="8A", to_camelot="2A", from_bpm=120.0, to_bpm=130.0)
    assert res_clash6["harmonic_type"] == "clash"
    assert res_clash6["harmonic_badge"] == "clash"
    assert res_clash6["relation_label"] == "8A -> 2A [Harmonic Clash +6]"
    assert res_clash6["clash_level"] == 2


def test_evaluate_harmonic_transition_tempo_categories():
    """Verify BPM delta classifications into Smooth Lock, Mixable, Moderate Shift, and Tempo Jump."""
    # Smooth Lock (< 1.5%)
    res_lock = evaluate_harmonic_transition(from_camelot="8A", to_camelot="8A", from_bpm=120.0, to_bpm=121.0)
    assert res_lock["bpm_status"] == "Smooth Lock"
    assert res_lock["bpm_badge"] == "score-high"

    # Mixable (1.5% to 4.0%)
    res_mix = evaluate_harmonic_transition(from_camelot="8A", to_camelot="8A", from_bpm=120.0, to_bpm=124.0)
    assert res_mix["bpm_status"] == "Mixable"
    assert res_mix["bpm_badge"] == "score-high"

    # Moderate Shift (4.0% to 8.0%)
    res_mod = evaluate_harmonic_transition(from_camelot="8A", to_camelot="8A", from_bpm=120.0, to_bpm=128.0)
    assert res_mod["bpm_status"] == "Moderate Shift"
    assert res_mod["bpm_badge"] == "score-mid"

    # Tempo Jump (> 8.0%)
    res_jump = evaluate_harmonic_transition(from_camelot="8A", to_camelot="8A", from_bpm=120.0, to_bpm=140.0)
    assert res_jump["bpm_status"] == "Tempo Jump"
    assert res_jump["bpm_badge"] == "score-low"

    # Unknown key neutral fallback
    res_unk = evaluate_harmonic_transition(from_camelot=None, to_camelot="8A")
    assert res_unk["harmonic_type"] == "unknown"
    assert res_unk["harmonic_score"] == 70.0


def test_calculate_transition_metrics_and_summary():
    """Verify transition metrics sequence evaluation and playlist summary aggregation."""
    tracks = [
        {"track_id": 1, "title": "Track 1", "artist": "Artist A", "duration": 180.0, "bpm": 120.0, "key": "A", "scale": "minor"}, # 8A
        {"track_id": 2, "title": "Track 2", "artist": "Artist A", "duration": 200.0, "bpm": 120.5, "key": "A", "scale": "minor"}, # 8A (seamless)
        {"track_id": 3, "title": "Track 3", "artist": "Artist B", "duration": 220.0, "bpm": 122.0, "key": "E", "scale": "minor"}, # 9A (+1 boost)
        {"track_id": 4, "title": "Track 4", "artist": "Artist C", "duration": 190.0, "bpm": 126.0, "key": "G", "scale": "minor"}, # 6A (clash -2)
    ]

    metrics = calculate_transition_metrics(tracks)
    assert len(metrics) == 3

    # Transition 1: 1 -> 2
    assert metrics[0]["from_track_id"] == 1
    assert metrics[0]["to_track_id"] == 2
    assert metrics[0]["harmonic_badge"] == "seamless"

    # Transition 2: 2 -> 3
    assert metrics[1]["from_track_id"] == 2
    assert metrics[1]["to_track_id"] == 3
    assert metrics[1]["harmonic_badge"] == "harmonic-boost"

    # Transition 3: 3 -> 4
    assert metrics[2]["from_track_id"] == 3
    assert metrics[2]["to_track_id"] == 4
    assert metrics[2]["harmonic_badge"] == "clash"

    # Aggregate summary
    summary = calculate_playlist_summary(tracks, metrics)
    assert summary["track_count"] == 4
    assert summary["total_duration"] == 790.0
    assert summary["seamless_count"] == 1
    assert summary["boost_count"] == 1
    assert summary["clash_count"] == 1
    assert summary["avg_transition_score"] > 0


def test_evaluate_energy_arc_variants():
    """Verify all 4 named journey arcs evaluate correctly."""
    # Energy Ramp: ascending
    ramp_start = evaluate_energy_arc("energy_ramp", 0, 10)
    ramp_end = evaluate_energy_arc("energy_ramp", 9, 10)
    assert ramp_start < 0.35
    assert ramp_end > 0.85

    # Peak-Hour Wave: apex in middle
    wave_start = evaluate_energy_arc("peak_hour_wave", 0, 10)
    wave_mid = evaluate_energy_arc("peak_hour_wave", 5, 10)
    wave_end = evaluate_energy_arc("peak_hour_wave", 9, 10)
    assert wave_mid > wave_start
    assert wave_mid > wave_end

    # Steady Pulse: consistent plateau
    assert evaluate_energy_arc("steady_pulse", 0, 10) == 0.60
    assert evaluate_energy_arc("steady_pulse", 5, 10) == 0.60
    assert evaluate_energy_arc("steady_pulse", 9, 10) == 0.60

    # Late Night Chill: descending calm
    chill_start = evaluate_energy_arc("late_night_chill", 0, 10)
    chill_end = evaluate_energy_arc("late_night_chill", 9, 10)
    assert chill_start > chill_end
    assert chill_end <= 0.25


def test_web_api_builder_search(test_env):
    """Verify GET /api/playlist/builder/search returns matches with telemetry in both HTML and JSON."""
    _, _, _, client = test_env

    # 1. HTML Search mode
    resp_html = client.get("/api/playlist/builder/search?q=Aura")
    assert resp_html.status_code == 200
    html_text = resp_html.text
    assert "Deep Awakening" in html_text
    assert "Celestial Drift" in html_text
    assert "8A" in html_text
    assert "8B" in html_text
    assert "seed-result-item" in html_text

    # 2. JSON Search mode
    resp_json = client.get("/api/playlist/builder/search?q=Aura&format=json")
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert "results" in data
    assert len(data["results"]) == 2
    assert data["results"][0]["artist"] == "Aura"
    assert data["results"][0]["camelot"] in ("8A", "8B")


def test_web_api_builder_preview(test_env):
    """Verify POST /api/playlist/builder/preview generates sequence and harmonic transition cards."""
    _, _, _, client = test_env

    payload = {
        "seed_track_id": 1,
        "arc": "energy_ramp",
        "limit": 4,
        "max_bpm_delta": 10.0,
        "max_artist_tracks": 2,
        "name": "Harmonic Journey Test",
    }

    # 1. HTML preview mode
    resp_html = client.post("/api/playlist/builder/preview", data=payload)
    assert resp_html.status_code == 200
    text = resp_html.text
    assert "guided-playlist-builder-root" in text
    assert "Harmonic Journey Test" in text
    assert "Harmonic Summary:" in text
    assert "transition-connector" in text

    # 2. JSON preview mode
    resp_json = client.post(
        "/api/playlist/builder/preview",
        data=payload,
        headers={"Accept": "application/json"},
    )
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert "playlist" in data
    assert "transitions" in data
    assert "summary" in data
    assert len(data["playlist"]["tracks"]) >= 2
    assert len(data["transitions"]) == len(data["playlist"]["tracks"]) - 1


def test_web_api_builder_reorder(test_env):
    """Verify POST /api/playlist/builder/reorder updates sequence and dynamically recalculates transitions."""
    db_file, _, _, client = test_env

    # First, generate a playlist so it exists in DB
    gen_resp = client.post(
        "/api/playlist/builder/preview",
        data={
            "seed_track_id": 1,
            "arc": "steady_pulse",
            "limit": 4,
            "max_bpm_delta": 15.0,
            "max_artist_tracks": 2,
            "name": "Reorder Test Session",
        },
        headers={"Accept": "application/json"},
    )
    assert gen_resp.status_code == 200
    pl_data = gen_resp.json()["playlist"]
    pl_id = pl_data["playlist_id"]
    orig_tracks = [t["track_id"] for t in pl_data["tracks"]]

    # Reverse the track order
    reversed_tracks = list(reversed(orig_tracks))
    reorder_payload = {
        "playlist_id": pl_id,
        "track_ids": ",".join(map(str, reversed_tracks)),
        "step": 4,
    }

    # Test reorder via API
    resp_reorder = client.post(
        "/api/playlist/builder/reorder",
        data=reorder_payload,
        headers={"Accept": "application/json"},
    )
    assert resp_reorder.status_code == 200
    reorder_data = resp_reorder.json()
    new_tracks = [t["track_id"] for t in reorder_data["playlist"]["tracks"]]
    assert new_tracks == reversed_tracks

    # Verify transitions recalculation
    assert len(reorder_data["transitions"]) == len(reversed_tracks) - 1
    for tr in reorder_data["transitions"]:
        assert "relation_label" in tr
        assert "total_score" in tr
        assert "harmonic_badge" in tr

    # Verify database persistence
    with get_connection(db_file) as conn:
        db_tracks = get_playlist_tracks(conn, pl_id)
        db_ids = [t["track_id"] for t in db_tracks]
        assert db_ids == reversed_tracks


def test_stepper_elements_and_draggable_contract(test_env):
    """Verify 4-step wizard markup contracts and native draggable attributes."""
    _, _, _, client = test_env

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text

    # Stepper navigation IDs
    assert 'id="pill-step-1"' in body
    assert 'id="pill-step-2"' in body
    assert 'id="pill-step-3"' in body
    assert 'id="pill-step-4"' in body

    # Stepper panels
    assert 'id="builder-step-1"' in body
    assert 'id="builder-step-2"' in body
    assert 'id="builder-step-3"' in body
    assert 'id="builder-step-4"' in body

    # Arc cards
    assert 'value="energy_ramp"' in body
    assert 'value="peak_hour_wave"' in body
    assert 'value="steady_pulse"' in body
    assert 'value="late_night_chill"' in body

    # Draggable tracks list container contract
    assert 'id="playlist-tracks-list"' in body
