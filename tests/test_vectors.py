"""Tests for vibe vector formulation, similarity search, caching, and clustering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from vibeplay.config import Settings
from vibeplay.db import (
    get_connection,
    init_db,
    insert_or_replace_features,
    insert_track,
)
from vibeplay.vectors import (
    ClusteringResult,
    build_vibe_vectors,
    compute_clusters,
    get_or_build_vibe_vectors,
    similar_to,
)


@pytest.fixture
def sample_settings(tmp_path: Path) -> Settings:
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


def make_synthetic_track_data(
    track_id: int,
    bpm: float,
    loudness: float = -8.0,
    danceability: float = 0.6,
    energy: float = 0.7,
    mood_scores: dict[str, float] | None = None,
    embedding: np.ndarray | None = None,
    title: str = "Test Title",
    artist: str = "Test Artist",
    album: str = "Test Album",
) -> dict[str, Any]:
    """Helper to generate synthetic track feature records."""
    default_moods = {
        "happy": 0.5,
        "sad": 0.2,
        "relaxed": 0.3,
        "aggressive": 0.4,
        "party": 0.6,
        "acoustic": 0.1,
        "electronic": 0.8,
    }
    moods = mood_scores or default_moods
    emb = embedding if embedding is not None else np.random.RandomState(track_id).randn(128).astype(np.float32)

    return {
        "track_id": track_id,
        "bpm": bpm,
        "loudness": loudness,
        "danceability": danceability,
        "energy": energy,
        "mood_scores": moods,
        "embedding": emb.tobytes(),
        "title": f"{title} {track_id}",
        "artist": artist,
        "album": album,
        "path": f"/music/{artist}/{album}/{track_id}.mp3",
    }


def populate_test_db(settings: Settings, track_records: list[dict[str, Any]]) -> None:
    """Helper to populate SQLite test database with tracks and audio features."""
    init_db(settings.db_path)
    with get_connection(settings.db_path) as conn:
        for rec in track_records:
            tid = rec["track_id"]
            inserted_id = insert_track(
                conn=conn,
                path=rec["path"],
                mtime=1700000000.0,
                size=5000000,
                file_hash=f"hash_{tid}",
                duration=210.0,
                bitrate=320000,
                has_cover=False,
                title=rec["title"],
                artist=rec["artist"],
                album=rec["album"],
            )
            insert_or_replace_features(
                conn=conn,
                track_id=inserted_id,
                analyzer_version="test-1.0",
                bpm=rec["bpm"],
                key="C",
                scale="major",
                loudness=rec["loudness"],
                danceability=rec["danceability"],
                energy=rec["energy"],
                mood_scores_json=json.dumps(rec["mood_scores"]) if isinstance(rec["mood_scores"], dict) else rec["mood_scores"],
                embedding_blob=rec["embedding"] if isinstance(rec["embedding"], (bytes, bytearray)) else rec["embedding"].tobytes(),
            )
        conn.commit()


def test_bpm_half_double_time_harmonic_similarity(sample_settings: Settings) -> None:
    """Test that 70 BPM and 140 BPM have high harmonic similarity compared to unrelated BPM."""
    # 1. Pure harmonic weighting (bpm_harmonic_weight=1.0)
    pure_cfg = sample_settings.model_copy(update={"bpm_harmonic_weight": 1.0})
    shared_emb = np.random.RandomState(42).randn(128).astype(np.float32)
    t1 = make_synthetic_track_data(1, bpm=70.0, embedding=shared_emb)
    t2 = make_synthetic_track_data(2, bpm=140.0, embedding=shared_emb)
    t3 = make_synthetic_track_data(3, bpm=105.0, embedding=shared_emb)

    _, vectors_pure, _ = build_vibe_vectors([t1, t2, t3], settings=pure_cfg)
    pure_sim_70_140 = float(np.dot(vectors_pure[0], vectors_pure[1]))
    pure_sim_70_105 = float(np.dot(vectors_pure[0], vectors_pure[2]))

    # Pure harmonic representation gives identical unit vectors for 70 and 140
    assert pytest.approx(pure_sim_70_140, abs=1e-5) == 1.0
    assert pure_sim_70_105 < 0.0

    # 2. Composite weighting (harmonic angle + slight absolute tempo)
    _, vectors_comp, _ = build_vibe_vectors([t1, t2, t3], settings=sample_settings)
    comp_sim_70_140 = float(np.dot(vectors_comp[0], vectors_comp[1]))
    comp_sim_70_105 = float(np.dot(vectors_comp[0], vectors_comp[2]))

    # Half/double-time pair remains much more similar than unrelated tempo pair
    assert comp_sim_70_140 > comp_sim_70_105
    assert comp_sim_70_140 > 0.0
    assert comp_sim_70_105 < 0.0


def test_vibe_vector_l2_normalization(sample_settings: Settings) -> None:
    """Verify that all generated vibe vectors are strictly unit L2 normalized."""
    records = [make_synthetic_track_data(i, bpm=80.0 + i * 15.0, energy=0.1 * i, danceability=0.2 * i) for i in range(1, 10)]
    _, vectors, _ = build_vibe_vectors(records, settings=sample_settings)

    norms = np.linalg.norm(vectors, axis=1)
    for norm in norms:
        assert pytest.approx(norm, abs=1e-5) == 1.0


def test_similar_to_ranking(sample_settings: Settings) -> None:
    """Test nearest-neighbor search ranking, tuple unpacking, and object attributes."""
    records = [
        make_synthetic_track_data(1, bpm=120.0, energy=0.9, danceability=0.9, artist="DanceAct"),
        make_synthetic_track_data(2, bpm=121.0, energy=0.88, danceability=0.89, artist="DanceAct"),
        make_synthetic_track_data(3, bpm=70.0, energy=0.2, danceability=0.3, artist="ChillAct"),
        make_synthetic_track_data(4, bpm=72.0, energy=0.22, danceability=0.31, artist="ChillAct"),
    ]
    populate_test_db(sample_settings, records)

    results = similar_to(track_id=1, n=2, settings=sample_settings)

    assert len(results) == 2
    # Track 1 should match Track 2 best
    assert results[0].track_id == 2
    assert results[0].artist == "DanceAct"
    assert results[0].similarity > results[1].similarity

    # Tuple unpacking test
    top_id, top_sim = results[0]
    assert top_id == 2
    assert isinstance(top_sim, float)

    # Non-existent track ID raises ValueError
    with pytest.raises(ValueError, match="not found"):
        similar_to(track_id=999, settings=sample_settings)


def test_kmeans_clustering(sample_settings: Settings) -> None:
    """Test KMeans clustering outputs valid cluster counts, summaries, and representatives."""
    records = []
    # Cluster A: Fast electronic (tracks 1-5)
    for i in range(1, 6):
        records.append(make_synthetic_track_data(i, bpm=130.0 + i, energy=0.9, danceability=0.8, artist="ClubCrew"))
    # Cluster B: Slow acoustic (tracks 6-10)
    for i in range(6, 11):
        records.append(make_synthetic_track_data(i, bpm=65.0 + i, energy=0.2, danceability=0.3, artist="FolkTrio"))

    populate_test_db(sample_settings, records)

    result = compute_clusters(k=2, algorithm="kmeans", settings=sample_settings)

    assert isinstance(result, ClusteringResult)
    assert result.total_tracks == 10
    assert len(result.clusters) == 2

    for cluster in result.clusters:
        assert cluster.size > 0
        assert cluster.avg_bpm > 0
        assert len(cluster.dominant_moods) > 0
        assert len(cluster.top_artists) > 0
        assert len(cluster.representative_tracks) > 0
        # Representative tracks should be sorted by similarity descending
        rep_sims = [r["similarity_to_centroid"] for r in cluster.representative_tracks]
        assert rep_sims == sorted(rep_sims, reverse=True)


def test_hdbscan_clustering(sample_settings: Settings) -> None:
    """Test HDBSCAN clustering runs and generates cluster summaries."""
    records = []
    for i in range(1, 15):
        records.append(make_synthetic_track_data(i, bpm=90.0 + (i % 3) * 30.0, energy=0.1 * (i % 10)))

    populate_test_db(sample_settings, records)

    result = compute_clusters(algorithm="hdbscan", min_cluster_size=3, settings=sample_settings)

    assert isinstance(result, ClusteringResult)
    assert result.total_tracks == 14
    assert len(result.clusters) >= 1


def test_vector_cache_persistence_and_invalidation(sample_settings: Settings) -> None:
    """Test that vibe vectors are cached to disk and invalidated when features or settings change."""
    records = [
        make_synthetic_track_data(1, bpm=120.0),
        make_synthetic_track_data(2, bpm=125.0),
    ]
    populate_test_db(sample_settings, records)

    cache_file = sample_settings.get_vector_cache_path()
    assert not cache_file.exists()

    # 1. Initial build creates cache file
    tids1, vecs1, _ = get_or_build_vibe_vectors(settings=sample_settings)
    assert cache_file.exists()
    assert len(tids1) == 2

    # 2. Second call loads from cache file
    tids2, vecs2, _ = get_or_build_vibe_vectors(settings=sample_settings)
    np.testing.assert_array_equal(tids1, tids2)
    np.testing.assert_array_almost_equal(vecs1, vecs2)

    # 3. Modify feature in DB -> cache invalidation
    with get_connection(sample_settings.db_path) as conn:
        insert_or_replace_features(
            conn=conn,
            track_id=1,
            analyzer_version="test-1.0",
            bpm=160.0,  # Changed BPM
            key="C",
            scale="major",
            loudness=-5.0,
            danceability=0.8,
            energy=0.9,
            mood_scores_json=json.dumps({"happy": 0.9}),
            embedding_blob=np.zeros(128, dtype=np.float32).tobytes(),
        )
        conn.commit()

    tids3, vecs3, _ = get_or_build_vibe_vectors(settings=sample_settings)
    # Vector for track 1 should have changed
    assert not np.allclose(vecs1[0], vecs3[0])

    # 4. Modify settings weights -> cache invalidation
    modified_settings = sample_settings.model_copy(update={"weight_bpm": 5.0})
    tids4, vecs4, _ = get_or_build_vibe_vectors(settings=modified_settings)
    assert not np.allclose(vecs3[0], vecs4[0])


def test_edge_cases_empty_and_single_track(sample_settings: Settings) -> None:
    """Test edge cases with empty dataset and single track."""
    # Empty
    tids, vecs, meta = build_vibe_vectors([], settings=sample_settings)
    assert len(tids) == 0
    assert len(vecs) == 0
    assert meta == {}

    # Single track (PCA and StandardScaler edge cases)
    single = [make_synthetic_track_data(1, bpm=120.0)]
    tids, vecs, meta = build_vibe_vectors(single, settings=sample_settings)
    assert len(tids) == 1
    assert vecs.shape[0] == 1
    assert pytest.approx(np.linalg.norm(vecs[0]), abs=1e-5) == 1.0
