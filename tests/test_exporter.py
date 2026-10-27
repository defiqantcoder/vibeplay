"""Tests for playlist exporter in M3U8, M3U, JSON, and CSV formats."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from vibeplay.db import (
    add_tracks_to_playlist,
    create_playlist,
    get_connection,
    init_db,
    insert_track,
)
from vibeplay.exporter import export_playlist_to_file


@pytest.fixture
def populated_db(tmp_path: Path) -> tuple[Path, int]:
    """Create a temporary database with tracks and a saved playlist."""
    db_file = tmp_path / "test_export.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        insert_track(
            conn,
            path=str(tmp_path / "music" / "Track1.flac"),
            mtime=1700000000.0,
            size=10000000,
            file_hash="h1",
            duration=215.4,
            title="Ocean Avenue",
            artist="Yellowcard",
            album="Ocean Avenue",
            genre="Pop Punk",
            year=2003,
        )
        insert_track(
            conn,
            path=str(tmp_path / "music" / "Track2.flac"),
            mtime=1700000001.0,
            size=12000000,
            file_hash="h2",
            duration=198.2,
            title="Way Away",
            artist="Yellowcard",
            album="Ocean Avenue",
            genre="Pop Punk",
            year=2003,
        )
        pid = create_playlist(
            conn=conn,
            name="Yellowcard Best",
            description="High energy summer punk",
            rules_json=json.dumps({"mode": "seed"}),
        )
        add_tracks_to_playlist(conn, pid, [1, 2])

    return db_file, pid


def test_export_m3u8_absolute(populated_db: tuple[Path, int], tmp_path: Path) -> None:
    """Verify exporting M3U8 with absolute track file paths."""
    db_file, pid = populated_db
    out_file = tmp_path / "export" / "playlist.m3u8"

    exported = export_playlist_to_file(
        db_path=db_file,
        playlist_id=pid,
        output_path=out_file,
        export_format="m3u8",
        relative=False,
    )

    assert exported.exists()
    content = exported.read_text(encoding="utf-8")
    assert content.startswith("#EXTM3U\n")
    assert "#EXTINF:215,Yellowcard - Ocean Avenue" in content
    assert "#EXTINF:198,Yellowcard - Way Away" in content
    assert str(tmp_path / "music" / "Track1.flac") in content


def test_export_m3u8_relative(populated_db: tuple[Path, int], tmp_path: Path) -> None:
    """Verify exporting M3U8 with relative file paths."""
    db_file, pid = populated_db
    out_file = tmp_path / "export" / "playlist.m3u8"

    exported = export_playlist_to_file(
        db_path=db_file,
        playlist_id=pid,
        output_path=out_file,
        export_format="m3u8",
        relative=True,
    )

    assert exported.exists()
    content = exported.read_text(encoding="utf-8")
    assert content.startswith("#EXTM3U\n")
    # Relative path from tmp_path/export to tmp_path/music/Track1.flac is ../music/Track1.flac
    assert "../music/Track1.flac" in content


def test_export_json(populated_db: tuple[Path, int], tmp_path: Path) -> None:
    """Verify exporting playlist in structured JSON format."""
    db_file, pid = populated_db
    out_file = tmp_path / "export" / "playlist.json"

    exported = export_playlist_to_file(
        db_path=db_file,
        playlist_id=pid,
        output_path=out_file,
        export_format="json",
    )

    assert exported.exists()
    data = json.loads(exported.read_text(encoding="utf-8"))
    assert data["id"] == pid
    assert data["name"] == "Yellowcard Best"
    assert data["track_count"] == 2
    assert len(data["tracks"]) == 2
    assert data["tracks"][0]["title"] == "Ocean Avenue"
    assert data["tracks"][1]["title"] == "Way Away"


def test_export_csv(populated_db: tuple[Path, int], tmp_path: Path) -> None:
    """Verify exporting playlist in standard CSV format."""
    db_file, pid = populated_db
    out_file = tmp_path / "export" / "playlist.csv"

    exported = export_playlist_to_file(
        db_path=db_file,
        playlist_id=pid,
        output_path=out_file,
        export_format="csv",
    )

    assert exported.exists()
    with out_file.open(newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 2
        assert reader[0]["title"] == "Ocean Avenue"
        assert reader[0]["artist"] == "Yellowcard"
        assert reader[0]["position"] == "1"


def test_export_nonexistent_playlist_raises(populated_db: tuple[Path, int], tmp_path: Path) -> None:
    """Verify ValueError is raised when exporting an unknown playlist ID."""
    db_file, _ = populated_db
    out_file = tmp_path / "export" / "missing.m3u8"

    with pytest.raises(ValueError, match="Playlist with ID 9999 not found"):
        export_playlist_to_file(
            db_path=db_file,
            playlist_id=9999,
            output_path=out_file,
        )


def test_export_unsupported_format_raises(populated_db: tuple[Path, int], tmp_path: Path) -> None:
    """Verify ValueError is raised for unsupported export formats."""
    db_file, pid = populated_db
    out_file = tmp_path / "export" / "bad.txt"

    with pytest.raises(ValueError, match="Unsupported playlist export format"):
        export_playlist_to_file(
            db_path=db_file,
            playlist_id=pid,
            output_path=out_file,
            export_format="yaml",
        )
