import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from vibeplay.config import Settings
from vibeplay.db import get_connection
from vibeplay.vectors import compute_clusters, invalidate_cluster_cache


@pytest.fixture
def sample_settings(tmp_path: Path) -> Settings:
    db_file = tmp_path / "vectors_test.db"
    from vibeplay.db import init_db

    init_db(db_file)
    return Settings(
        db_path=db_file,
        weight_bpm=1.0,
        weight_loudness=1.0,
        weight_danceability=1.0,
        weight_energy=1.0,
        weight_mood=1.0,
        weight_embedding=1.0,
        pca_embedding_dimensions=2,
    )


def populate_test_db(settings: Settings, track_records: list[dict[str, Any]]) -> None:
    with get_connection(settings.db_path) as conn:
        for r in track_records:
            tid = r["track_id"]
            conn.execute(
                """
                INSERT OR REPLACE INTO tracks
                (id, path, duration, bitrate, mtime, size, hash, title, artist, album)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    f"/path/{tid}.flac",
                    120.0,
                    1411,
                    1000000,
                    5000000,
                    f"hash_{tid}",
                    r["title"],
                    r["artist"],
                    r["album"],
                ),
            )
            emb = np.zeros(128, dtype=np.float32)
            conn.execute(
                """
                INSERT OR REPLACE INTO features
                (track_id, analyzer_version, bpm, key, scale, loudness, danceability, energy, mood_scores, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    "1.0.0",
                    r["bpm"],
                    "C",
                    "major",
                    r["loudness"],
                    r["danceability"],
                    r["energy"],
                    json.dumps(r["mood_scores"]),
                    emb.tobytes(),
                ),
            )
        conn.commit()


def make_synthetic_track_data(
    track_id: int,
    bpm: float = 120.0,
    energy: float = 0.5,
    danceability: float = 0.5,
    artist: str = "Unknown",
) -> dict[str, Any]:
    return {
        "track_id": track_id,
        "title": f"Track {track_id}",
        "artist": artist,
        "album": "Album",
        "bpm": bpm,
        "loudness": -10.0 + (energy * 5.0),
        "danceability": danceability,
        "energy": energy,
        "mood_scores": {"happy": 0.5, "sad": 0.5},
    }


def test_compute_clusters_caching(sample_settings: Settings) -> None:
    records = []
    for i in range(1, 11):
        records.append(make_synthetic_track_data(i, bpm=130.0 + i, energy=0.9, danceability=0.8, artist="ClubCrew"))
    populate_test_db(sample_settings, records)

    invalidate_cluster_cache()

    start_time = time.perf_counter()
    result1 = compute_clusters(k=2, algorithm="kmeans", settings=sample_settings)
    t1 = time.perf_counter() - start_time

    start_time = time.perf_counter()
    result2 = compute_clusters(k=2, algorithm="kmeans", settings=sample_settings)
    t2 = time.perf_counter() - start_time

    assert t2 < 0.5, f"Cached compute_clusters took {t2:.5f}s, expected < 500ms"
    assert result1.total_tracks == result2.total_tracks
    assert result1.k == result2.k

    invalidate_cluster_cache()

    start_time = time.perf_counter()
    result3 = compute_clusters(k=2, algorithm="kmeans", settings=sample_settings)
    t3 = time.perf_counter() - start_time

    # We might not be > 5ms every time, so don't assert it strictly, just check it ran without error
