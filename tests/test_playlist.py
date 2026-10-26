"""Comprehensive tests for smart playlist generation, harmonic mixing, and constraints."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

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
    bpm_transition_score,
    camelot_distance,
    camelot_key_score,
    evaluate_energy_arc,
    fold_bpm,
    generate_playlist,
    key_to_camelot,
)


@pytest.fixture
def playlist_settings(tmp_path: Path) -> Settings:
    """Fixture providing isolated Settings with temporary DB and cache paths."""
    db_file = tmp_path / "test_vibeplay.db"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
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


def test_key_to_camelot_mappings() -> None:
    """Verify Camelot Wheel key parsing and mode recognition."""
    assert key_to_camelot("C", "major") == "8B"
    assert key_to_camelot("C", None) == "8B"
    assert key_to_camelot("A", "minor") == "8A"
    assert key_to_camelot("Am", None) == "8A"
    assert key_to_camelot("A minor", None) == "8A"
    assert key_to_camelot("C#m", None) == "12A"
    assert key_to_camelot("F#", "minor") == "11A"
    assert key_to_camelot("Gb", "major") == "2B"
    assert key_to_camelot(None, None) is None
    assert key_to_camelot("UnknownKey", None) is None


def test_camelot_distance_and_scores() -> None:
    """Verify circular harmonic distances and transition scores on Camelot wheel."""
    # Identical keys
    assert camelot_distance("8B", "8B") == 0
    assert camelot_key_score("8B", "8B") == 1.0

    # Adjacent key (+1 step)
    assert camelot_distance("8B", "9B") == 1
    assert camelot_key_score("8B", "9B") == 0.95

    # Relative minor / major (same number, mode switch)
    assert camelot_distance("8B", "8A") == 1
    assert camelot_key_score("8B", "8A") == 0.95

    # 2 steps away
    assert camelot_distance("8A", "10A") == 2
    assert camelot_key_score("8A", "10A") == 0.70

    # Maximum circular distance (opposite side of wheel)
    assert camelot_distance("8A", "2A") == 6
    assert camelot_key_score("8A", "2A") == 0.20

    # Unknown key is neutral
    assert camelot_key_score(None, "8B") == 0.70
    assert camelot_key_score("8A", None) == 0.70


def test_fold_bpm_and_transition_score() -> None:
    """Verify octave folding for tempos and transition smoothness."""
    assert fold_bpm(70.0) == 140.0
    assert fold_bpm(140.0) == 140.0
    assert fold_bpm(280.0) == 140.0
    assert fold_bpm(85.0) == 85.0
    assert fold_bpm(170.0) == 85.0

    # 70 and 140 BPM have identical folded tempo: 1.0 score
    assert bpm_transition_score(70.0, 140.0) == 1.0

    # 15 BPM difference in folded domain -> 0.5 score
    assert abs(bpm_transition_score(120.0, 135.0) - 0.5) < 1e-4

    # >=30 BPM difference -> 0.0 score
    assert bpm_transition_score(100.0, 130.0) == 0.0

    # Missing tempo fallback
    assert bpm_transition_score(None, 120.0) == 0.7


def test_evaluate_energy_arcs() -> None:
    """Verify energy trajectory evaluations for various arcs."""
    # Ramp up: starts low, ends high
    start_ramp = evaluate_energy_arc("ramp_up", 0, 10)
    end_ramp = evaluate_energy_arc("ramp_up", 9, 10)
    assert start_ramp < 0.35
    assert end_ramp > 0.80

    # Cooldown: starts high, ends low
    start_cool = evaluate_energy_arc("cooldown", 0, 10)
    end_cool = evaluate_energy_arc("cooldown", 9, 10)
    assert start_cool > 0.80
    assert end_cool < 0.35

    # Peak: low at ends, high at middle
    start_peak = evaluate_energy_arc("peak", 0, 10)
    mid_peak = evaluate_energy_arc("peak", 5, 10)
    end_peak = evaluate_energy_arc("peak", 9, 10)
    assert mid_peak > start_peak
    assert mid_peak > end_peak

    # Steady
    assert evaluate_energy_arc("steady", 4, 10) == 0.60


def _seed_test_database(db_file: Path) -> list[int]:
    """Helper to populate database with diverse synthetic tracks."""
    init_db(db_file)
    track_ids = []

    tracks_meta = [
        # (id, title, artist, album, duration, bpm, key, scale, energy, danceability, genre)
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
        ) in tracks_meta:
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
                "happy": 0.8 if "Party" in title or "Summer" in title else 0.3,
                "sad": 0.1,
                "relaxed": 0.8 if "Chill" in title or "Acoustic" in title else 0.2,
                "aggressive": 0.8 if "Rush" in title or "Overdrive" in title else 0.1,
                "party": 0.9 if "Party" in title else 0.2,
                "acoustic": 0.9 if "Acoustic" in title or "Rustic" in title else 0.1,
                "electronic": 0.9
                if genre == "Electronic" or genre == "Techno"
                else 0.1,
            }
            emb = np.sin(np.linspace(0, tid, 128)).astype(np.float32)
            insert_or_replace_features(
                conn,
                track_id=tid,
                analyzer_version="1.0.0",
                bpm=bpm,
                key=key,
                scale=scale,
                loudness=-10.0 + energy * 4.0,
                danceability=dance,
                energy=energy,
                mood_scores_json=json.dumps(moods),
                embedding_blob=emb.tobytes(),
            )
            track_ids.append(tid)

    return track_ids


def test_generate_playlist_seed_mode(playlist_settings: Settings) -> None:
    """Verify seed mode playlist generation and database persistence."""
    _seed_test_database(playlist_settings.db_path)

    playlist = generate_playlist(
        db_path=playlist_settings.db_path,
        name="Seed Chillout",
        seed_track_id=1,
        limit=5,
        settings=playlist_settings,
    )

    assert playlist.playlist_id > 0
    assert len(playlist.tracks) <= 5
    assert playlist.tracks[0].track_id == 1  # Starting track is seed
    assert playlist.avg_transition_score > 0.0

    # Verify database records
    with get_connection(playlist_settings.db_path) as conn:
        stored_pl = get_playlist(conn, playlist.playlist_id)
        assert stored_pl is not None
        assert stored_pl["name"] == "Seed Chillout"

        stored_tracks = get_playlist_tracks(conn, playlist.playlist_id)
        assert len(stored_tracks) == len(playlist.tracks)
        assert stored_tracks[0]["track_id"] == 1


def test_max_artist_tracks_constraint(playlist_settings: Settings) -> None:
    """Verify max_artist_tracks constraint prevents artist over-representation."""
    _seed_test_database(playlist_settings.db_path)

    # Solaris has 3 tracks in DB. With max_artist_tracks=1, at most 1 is picked.
    playlist = generate_playlist(
        db_path=playlist_settings.db_path,
        name="Diverse Artists",
        seed_track_id=1,
        limit=5,
        max_artist_tracks=1,
        settings=playlist_settings,
    )

    artist_counts: dict[str, int] = {}
    for t in playlist.tracks:
        artist_counts[t.artist] = artist_counts.get(t.artist, 0) + 1

    assert artist_counts.get("Solaris", 0) <= 1


def test_energy_arc_ramp_up(playlist_settings: Settings) -> None:
    """Verify ramp_up arc orders tracks with increasing energy levels."""
    _seed_test_database(playlist_settings.db_path)

    playlist = generate_playlist(
        db_path=playlist_settings.db_path,
        name="Ramp Up Energy",
        arc="ramp_up",
        limit=5,
        settings=playlist_settings,
    )

    assert len(playlist.tracks) >= 3
    # Beginning energy should be lower than ending energy
    first_energy = playlist.tracks[0].energy or 0.0
    last_energy = playlist.tracks[-1].energy or 0.0
    assert last_energy >= first_energy


def test_rules_filter_and_vibe_presets(playlist_settings: Settings) -> None:
    """Verify rule-based filtering with acoustic vibe preset."""
    _seed_test_database(playlist_settings.db_path)

    rules = PlaylistRuleConfig(
        mode="rules",
        vibe="acoustic",
        limit=3,
    )
    playlist = generate_playlist(
        db_path=playlist_settings.db_path,
        name="Acoustic Morning",
        rules=rules,
        settings=playlist_settings,
    )

    assert len(playlist.tracks) > 0
    for t in playlist.tracks:
        # Acoustic tracks in dataset are Echo Valley
        assert t.energy is not None and t.energy <= 0.65


def test_minutes_target_duration(playlist_settings: Settings) -> None:
    """Verify target minutes constraint terminates playlist when duration reached."""
    _seed_test_database(playlist_settings.db_path)

    # 6 minutes target (~360 seconds) with ~200s tracks -> should yield ~2 tracks
    playlist = generate_playlist(
        db_path=playlist_settings.db_path,
        name="Short Duration",
        seed_track_id=1,
        minutes=6.0,
        settings=playlist_settings,
    )

    assert 1 <= len(playlist.tracks) <= 3
    assert playlist.total_duration >= 360.0 or len(playlist.tracks) == 2

def test_playlist_engine_constraints(playlist_settings: Settings) -> None:
    import numpy as np

    from vibeplay.playlist import calculate_transition, evaluate_energy_arc

    assert evaluate_energy_arc("steady", 0, 10) == 0.60
    assert evaluate_energy_arc("steady", 5, 1) == 0.60
    assert evaluate_energy_arc("unknown_arc", 0, 10) == 0.60

    # Tests for calculating transition with None values
    trans = calculate_transition(None, {"track_id": 1})
    assert trans.from_track_id is None
    assert trans.to_track_id == 1
    assert trans.vibe_similarity == 1.0

    from_meta = {"track_id": 1, "bpm": 120.0, "key": "C", "scale": "major"}
    to_meta = {"track_id": 2, "bpm": 120.0, "key": "C", "scale": "major"}
    from_vec = np.array([1.0, 0.0])
    to_vec = np.array([1.0, 0.0])

    trans_valid = calculate_transition(from_meta, to_meta, from_vec, to_vec)
    assert trans_valid.vibe_similarity == 1.0
    assert trans_valid.bpm_score == 1.0
    assert trans_valid.key_score == 1.0

def test_key_to_camelot_more_edge_cases():
    from vibeplay.playlist import key_to_camelot
    assert key_to_camelot("", "") is None
    assert key_to_camelot(None, None) is None
    assert key_to_camelot("C minor", None) == "5A"
    assert key_to_camelot("C major", None) == "8B"
    assert key_to_camelot("C min", None) == "5A"
    assert key_to_camelot("C maj", None) == "8B"
    assert key_to_camelot("Am", None) == "8A"
    assert key_to_camelot("C#m", None) == "12A"

def test_generated_playlist_serialization():
    from vibeplay.playlist import GeneratedPlaylist, PlaylistTrackItem, TrackTransition

    trans = TrackTransition(1, 2, 0.9, 0.8, 0.7, 0.85)
    item = PlaylistTrackItem(
        position=1, track_id=2, title="T", artist="A", album="AL",
        duration=100.0, bpm=120.0, key="C", scale="major", camelot="8B",
        energy=0.8, danceability=0.7, path="/p", transition=trans
    )

    playlist = GeneratedPlaylist(
        playlist_id=1, name="Test", description="Desc", mode="seed",
        tracks=[item], total_duration=100.0, avg_transition_score=0.85
    )

    d = playlist.to_dict()
    assert d["playlist_id"] == 1
    assert d["name"] == "Test"
    assert len(d["tracks"]) == 1
    assert d["tracks"][0]["transition"]["total_score"] == 0.85

def test_generate_playlist_cluster_mode(playlist_settings: Settings) -> None:
    _seed_test_database(playlist_settings.db_path)
    from vibeplay.playlist import generate_playlist

    playlist = generate_playlist(
        db_path=playlist_settings.db_path,
        name="Cluster Based",
        cluster_id=0,
        limit=5,
        settings=playlist_settings
    )
    assert playlist.playlist_id > 0
