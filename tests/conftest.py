"""Shared pytest fixtures and test data generators for vibeplay test suite."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from vibeplay.db import get_connection, init_db, insert_or_replace_features, insert_track


@pytest.fixture
def seed_test_database():
    """Factory fixture to populate database with diverse synthetic tracks."""

    def _seed(db_file: Path) -> list[int]:
        init_db(db_file)
        track_ids = []

        tracks_meta = [
            (1, "Summer Breeze", "Solaris", "Heatwave", 200.0, 120.0, "C", "major", 0.3, 0.4, "Ambient"),
            (2, "Sunset Chill", "Solaris", "Heatwave", 210.0, 122.0, "G", "major", 0.4, 0.5, "Ambient"),
            (3, "Overdrive", "Solaris", "Heatwave", 180.0, 128.0, "D", "major", 0.5, 0.6, "Rock"),
            (4, "Nightfall", "Lunar", "Orbit", 240.0, 124.0, "A", "minor", 0.6, 0.7, "Electronic"),
            (5, "Starlight", "Lunar", "Orbit", 195.0, 126.0, "E", "minor", 0.7, 0.8, "Electronic"),
            (6, "Cosmic Pulse", "Apex", "Peak Time", 220.0, 130.0, "B", "minor", 0.8, 0.9, "Techno"),
            (7, "Final Rush", "Apex", "Peak Time", 210.0, 132.0, "F#", "minor", 0.9, 0.85, "Techno"),
            (8, "Acoustic Morning", "Echo Valley", "Roots", 175.0, 95.0, "C", "major", 0.25, 0.3, "Folk"),
            (9, "Rustic Strings", "Echo Valley", "Roots", 190.0, 100.0, "G", "major", 0.35, 0.35, "Folk"),
            (10, "Party Rock", "The Dynamos", "Groove", 185.0, 125.0, "F", "major", 0.85, 0.8, "Dance"),
        ]

        with get_connection(db_file) as conn:
            for tid, title, artist, album, dur, bpm, key, scale, energy, dance, genre in tracks_meta:
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
                    "electronic": 0.9 if genre == "Electronic" or genre == "Techno" else 0.1,
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

    return _seed
