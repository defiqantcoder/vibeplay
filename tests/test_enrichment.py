"""Unit tests for metadata enrichment with mocked network calls."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from vibeplay.cli import app
from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db, insert_track
from vibeplay.plugins.maintenance.enrichment import (
    cached_acoustid_lookup,
    enrich_tracks,
    resolve_track_enrichment,
)

runner = CliRunner()


@pytest.fixture
def test_db_with_track(tmp_path: Path) -> Path:
    """Fixture providing an initialized SQLite database with one active track."""
    db_path = tmp_path / "vibeplay_enrich_test.db"
    init_db(db_path)

    # Create dummy audio file so Path.stat() works
    dummy_audio = tmp_path / "song.mp3"
    dummy_audio.write_bytes(b"dummy audio content")

    with get_connection(db_path) as conn:
        insert_track(
            conn=conn,
            path=str(dummy_audio),
            mtime=1700000000.0,
            size=len(dummy_audio.read_bytes()),
            file_hash="dummyhash123",
            duration=210.0,
            bitrate=320000,
            title="Original Title",
            artist="Original Artist",
            album_artist="Original Artist",
            album="Original Album",
            track_no=1,
            track_total=10,
            disc_no=1,
            disc_total=1,
            year=2020,
            genre="Rock",
            has_cover=False,
            tags_json=json.dumps({"title": ["Original Title"], "artist": ["Original Artist"]}),
        )

    return db_path


MOCK_ACOUSTID_HIGH_CONFIDENCE = {
    "status": "ok",
    "results": [
        {
            "id": "acoustid-123",
            "score": 0.95,
            "recordings": [
                {
                    "id": "mb-rec-123",
                    "title": "Canonical Title",
                    "artists": [{"id": "mb-art-123", "name": "Canonical Artist"}],
                    "releases": [
                        {
                            "id": "mb-rel-123",
                            "title": "Canonical Album",
                            "status": "Official",
                            "date": "2023-05-15",
                        }
                    ],
                }
            ],
        }
    ],
}

MOCK_ACOUSTID_LOW_CONFIDENCE = {
    "status": "ok",
    "results": [
        {
            "id": "acoustid-456",
            "score": 0.65,
            "recordings": [
                {
                    "id": "mb-rec-456",
                    "title": "Low Conf Title",
                    "artists": [{"id": "mb-art-456", "name": "Low Conf Artist"}],
                }
            ],
        }
    ],
}

MOCK_MUSICBRAINZ_RECORDING = {
    "recording": {
        "id": "mb-rec-123",
        "title": "Canonical Title",
        "artist-credit-phrase": "Canonical Artist",
        "artist-credit": [
            {
                "artist": {
                    "id": "mb-art-123",
                    "name": "Canonical Artist",
                    "tag-list": [{"name": "electronic pop", "count": "3"}],
                }
            }
        ],
        "release-list": [
            {
                "id": "mb-rel-123",
                "title": "Canonical Album",
                "status": "Official",
                "date": "2023-05-15",
                "tag-list": [{"name": "synthpop", "count": "2"}],
            }
        ],
        "tag-list": [{"name": "ambient", "count": "1"}],
    }
}


@patch("vibeplay.plugins.maintenance.enrichment.acoustid.fingerprint_file")
@patch("vibeplay.plugins.maintenance.enrichment.cached_acoustid_lookup")
@patch("vibeplay.plugins.maintenance.enrichment.cached_musicbrainz_recording")
def test_resolve_track_high_confidence(
    mock_mb: MagicMock,
    mock_acoustid: MagicMock,
    mock_fp: MagicMock,
    test_db_with_track: Path,
) -> None:
    """Verify that a high-confidence match is marked 'matched' and extracts canonical tags."""
    mock_fp.return_value = (210.0, b"fake-fingerprint-bytes")
    mock_acoustid.return_value = MOCK_ACOUSTID_HIGH_CONFIDENCE
    mock_mb.return_value = MOCK_MUSICBRAINZ_RECORDING

    with get_connection(test_db_with_track) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE id = 1")
        track = cursor.fetchone()

        result = resolve_track_enrichment(
            conn=conn,
            track=track,
            acoustid_api_key="test_api_key",
            confidence_threshold=0.8,
        )

        assert result.status == "matched"
        assert result.confidence == 0.95
        assert result.canonical_title == "Canonical Title"
        assert result.canonical_artist == "Canonical Artist"
        assert result.canonical_album == "Canonical Album"
        assert result.canonical_year == 2023
        assert result.mb_recording_id == "mb-rec-123"
        assert result.mb_release_id == "mb-rel-123"
        assert "electronic pop" in (result.genres_json or "")


@patch("vibeplay.plugins.maintenance.enrichment.acoustid.fingerprint_file")
@patch("vibeplay.plugins.maintenance.enrichment.cached_acoustid_lookup")
@patch("vibeplay.plugins.maintenance.enrichment.cached_musicbrainz_recording")
def test_resolve_track_low_confidence_needs_review(
    mock_mb: MagicMock,
    mock_acoustid: MagicMock,
    mock_fp: MagicMock,
    test_db_with_track: Path,
) -> None:
    """Verify that a match below threshold is marked 'needs_review'."""
    mock_fp.return_value = (210.0, b"fake-fingerprint-bytes")
    mock_acoustid.return_value = MOCK_ACOUSTID_LOW_CONFIDENCE
    mock_mb.return_value = None

    with get_connection(test_db_with_track) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE id = 1")
        track = cursor.fetchone()

        result = resolve_track_enrichment(
            conn=conn,
            track=track,
            acoustid_api_key="test_api_key",
            confidence_threshold=0.8,
        )

        assert result.status == "needs_review"
        assert result.confidence == 0.65
        assert result.canonical_title == "Low Conf Title"


@patch("vibeplay.plugins.maintenance.enrichment.acoustid.fingerprint_file")
@patch("vibeplay.plugins.maintenance.enrichment.cached_acoustid_lookup")
def test_resolve_track_unmatched(
    mock_acoustid: MagicMock,
    mock_fp: MagicMock,
    test_db_with_track: Path,
) -> None:
    """Verify that empty AcoustID results produce an 'unmatched' record."""
    mock_fp.return_value = (210.0, b"fake-fingerprint-bytes")
    mock_acoustid.return_value = {"status": "ok", "results": []}

    with get_connection(test_db_with_track) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE id = 1")
        track = cursor.fetchone()

        result = resolve_track_enrichment(
            conn=conn,
            track=track,
            acoustid_api_key="test_api_key",
            confidence_threshold=0.8,
        )

        assert result.status == "unmatched"
        assert result.confidence == 0.0
        assert result.canonical_title is None


def test_network_caching(test_db_with_track: Path) -> None:
    """Verify that network responses are saved in network_cache and reused."""
    with get_connection(test_db_with_track) as conn:
        with patch("vibeplay.plugins.maintenance.enrichment.acoustid.lookup") as mock_lookup:
            mock_lookup.return_value = {"status": "ok", "cached_test": True}

            # First call executes mock lookup
            res1 = cached_acoustid_lookup(conn, "key", b"fp_bytes_123", 100.0, max_retries=1)
            assert res1 == {"status": "ok", "cached_test": True}
            assert mock_lookup.call_count == 1

            # Second call should fetch from SQLite network_cache without calling lookup again
            res2 = cached_acoustid_lookup(conn, "key", b"fp_bytes_123", 100.0, max_retries=1)
            assert res2 == {"status": "ok", "cached_test": True}
            assert mock_lookup.call_count == 1


@patch("vibeplay.plugins.maintenance.enrichment.get_settings")
@patch("vibeplay.plugins.maintenance.enrichment.resolve_track_enrichment")
def test_enrich_tracks_batch(
    mock_resolve: MagicMock,
    mock_settings: MagicMock,
    test_db_with_track: Path,
) -> None:
    """Verify batch enrich_tracks updates database and produces accurate summary."""
    mock_settings.return_value = Settings(
        acoustid_api_key="dummy_api_key",
        enrichment_confidence_threshold=0.8,
    )
    from vibeplay.plugins.maintenance.enrichment import EnrichmentResult

    mock_resolve.return_value = EnrichmentResult(
        track_id=1,
        mb_recording_id="rec-1",
        mb_release_id="rel-1",
        mb_artist_id="art-1",
        canonical_title="Batch Title",
        canonical_artist="Batch Artist",
        canonical_album_artist="Batch Artist",
        canonical_album="Batch Album",
        canonical_year=2023,
        canonical_track_no=1,
        canonical_track_total=10,
        canonical_disc_no=1,
        canonical_disc_total=1,
        genres_json=json.dumps(["Electronic"]),
        tags_json=json.dumps(["ambient"]),
        confidence=0.92,
        status="matched",
        source="acoustid_musicbrainz",
        raw_metadata_json="{}",
    )

    summary = enrich_tracks(db_path=test_db_with_track)
    assert summary.total == 1
    assert summary.matched == 1
    assert summary.needs_review == 0
    assert summary.unmatched == 0
    assert summary.errors == 0

    # Verify best value view
    with get_connection(test_db_with_track) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title, artist, original_title, canonical_title FROM v_tracks_best_value WHERE track_id = 1")
        row = cursor.fetchone()
        assert row["title"] == "Batch Title"
        assert row["artist"] == "Batch Artist"
        assert row["original_title"] == "Original Title"
        assert row["canonical_title"] == "Batch Title"


def test_cli_enrich_report_empty(test_db_with_track: Path) -> None:
    """Verify that vibeplay enrich --report runs without errors."""
    result = runner.invoke(app, ["enrich", "--report", "--db", str(test_db_with_track)])
    assert result.exit_code == 0
    assert "Original Title" in result.stdout or "All active tracks" in result.stdout
