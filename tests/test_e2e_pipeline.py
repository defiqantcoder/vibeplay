from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from vibeplay.analysis import analyze_tracks
from vibeplay.config import get_settings
from vibeplay.db import get_connection, init_db
from vibeplay.desktop.settings import DesktopSettings, load_desktop_settings
from vibeplay.enrichment import enrich_tracks
from vibeplay.exporter import export_playlist_to_file
from vibeplay.playlist import PlaylistRuleConfig, generate_playlist
from vibeplay.scanner import scan_directory
from vibeplay.vectors import compute_clusters, get_or_build_vibe_vectors
from vibeplay.web import create_app


@pytest.fixture
def e2e_environment(tmp_path: Path) -> dict[str, Path]:
    library_path = tmp_path / "library"
    library_path.mkdir(exist_ok=True)
    db_path = tmp_path / "e2e.db"
    settings_path = tmp_path / "desktop_settings.json"

    # Create 4 distinct FLAC files
    sr = 44100
    durations = [3.0, 3.5, 4.0, 4.5]
    freqs = [440.0, 880.0, 1320.0, 1760.0]

    for i in range(4):
        dur = durations[i]
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        data = np.sin(2 * np.pi * freqs[i] * t).astype(np.float32)
        sf.write(str(library_path / f"track_{i}.flac"), data, sr)

    init_db(db_path)

    settings = DesktopSettings(alsa_device="hw:0,0")
    settings_path.write_text(settings.model_dump_json(indent=2))

    return {
        "library_path": library_path,
        "db_path": db_path,
        "settings_path": settings_path,
    }


def test_e2e_pipeline(e2e_environment: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    lib_path = e2e_environment["library_path"]
    db_path = e2e_environment["db_path"]
    settings_path = e2e_environment["settings_path"]

    # Mock settings path
    class MockSettings:
        def __init__(self, sp: Path) -> None:
            self.desktop_settings_path = sp
            self.acoustid_api_key = "dummy_key"
            self.enrichment_confidence_threshold = 0.8
            self.models_dir = Path("models")
            self.app_dir = Path("app")
            self.analyzer_window_seconds = 60.0
            self.db_path = Path("e2e.db")
            self.weight_bpm = 1.0
            self.weight_loudness = 1.0
            self.weight_danceability = 1.0
            self.weight_energy = 1.0
            self.weight_mood = 1.0
            self.weight_embedding = 1.0
            self.bpm_harmonic_weight = 1.0
            self.pca_embedding_dimensions = 8
            self.analyzer_workers = 1
            self.analyzer_backend = "essentia"
            self.theme_id = "god-of-ink"

        def get_desktop_settings_path(self, db_path: Path | None = None) -> Path:
            return self.desktop_settings_path

        @property
        def desktop_settings_path_prop(self) -> Path:
            return self.desktop_settings_path

        def get_vector_cache_path(self, db_path: Path) -> Path:
            return db_path.parent / "vectors.npz"

    monkeypatch.setattr("vibeplay.config.get_settings", lambda: MockSettings(settings_path))

    # Mock enrichment network calls
    def mock_cached_acoustid_lookup(*args, **kwargs):  # type: ignore
        # We need to simulate a valid response
        return {
            "results": [
                {
                    "score": 0.9,
                    "recordings": [
                        {
                            "id": "dummy_recording_id",
                            "title": "Mock Title",
                            "artists": [{"name": "Mock Artist"}],
                        }
                    ],
                }
            ]
        }

    def mock_cached_musicbrainz_recording(*args, **kwargs):  # type: ignore
        return {
            "title": "Canonical Mock Title",
            "artist-credit": [{"artist": {"name": "Canonical Mock Artist"}}],
            "releases": [{"title": "Mock Album", "date": "2024"}],
        }

    monkeypatch.setattr("vibeplay.enrichment.cached_acoustid_lookup", mock_cached_acoustid_lookup)
    monkeypatch.setattr(
        "vibeplay.enrichment.cached_musicbrainz_recording",
        mock_cached_musicbrainz_recording,
    )
    monkeypatch.setattr("acoustid.fingerprint_file", lambda f: (4.0, b"mock_fingerprint"))
    monkeypatch.setenv("ACOUSTID_API_KEY", "dummy_key")

    # Step 1: Scan
    scan_summary = scan_directory(lib_path, db_path)
    assert scan_summary.new == 4

    with get_connection(db_path) as conn:
        tracks = conn.execute("SELECT * FROM tracks").fetchall()
        assert len(tracks) == 4
        for t in tracks:
            assert t["hash"] is not None
            assert t["duration"] > 0

    # Step 2: Enrich
    enrich_summary = enrich_tracks(db_path)
    # They should all be matched or needs_review depending on the score, let's just assert they were processed
    assert (enrich_summary.matched + enrich_summary.needs_review) == 4

    with get_connection(db_path) as conn:
        enriched_view = conn.execute("SELECT * FROM v_tracks_best_value").fetchall()
        assert len(enriched_view) == 4

    # Step 3: Analyze
    analysis_summary = analyze_tracks(db_path, backend="librosa", workers=1)
    assert analysis_summary.analyzed == 4

    with get_connection(db_path) as conn:
        features = conn.execute("SELECT * FROM features").fetchall()
        assert len(features) == 4
        for f in features:
            assert f["embedding"] is not None

    # Step 4: Clusters
    _ = load_desktop_settings(settings_path)

    track_ids, vectors, meta_map = get_or_build_vibe_vectors(db_path)
    assert len(track_ids) == 4
    assert len(vectors) == 4

    app_settings = get_settings()
    clusters = compute_clusters(db_path, settings=app_settings)  # type: ignore
    assert len(clusters.clusters) > 0  # At least 1 cluster

    # Step 5: Playlist & Export
    rule_config = PlaylistRuleConfig(seed_track_ids=[int(track_ids[0])], target_duration_minutes=30)
    playlist = generate_playlist(db_path, rules=rule_config, settings=app_settings)  # type: ignore
    assert len(playlist.tracks) > 0

    export_path = Path(e2e_environment["library_path"]).parent / "playlist.m3u8"
    export_playlist_to_file(db_path, playlist.playlist_id, export_path)
    assert export_path.exists()
    content = export_path.read_text()
    assert "#EXTM3U" in content

    # Step 6: Web UI
    app_settings = get_settings()
    app = create_app(db_path=db_path, settings=app_settings, api_key="test_key")  # type: ignore
    client = TestClient(app)

    res_root = client.get("/", headers={"X-API-Key": "test_key"})
    assert res_root.status_code == 200

    res_clusters = client.get("/api/clusters/cards", headers={"X-API-Key": "test_key"})
    assert res_clusters.status_code == 200
    assert "cluster-card" in res_clusters.text

    res_generate = client.post(
        "/api/playlist/generate",
        json={"seed_track_ids": [int(track_ids[0])], "target_duration_minutes": 30},
        headers={"X-API-Key": "test_key"},
    )
    assert res_generate.status_code == 200
    assert "track" in res_generate.text
