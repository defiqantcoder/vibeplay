"""Tests for track update operations in db.py."""

import sqlite3
import json
from pathlib import Path

from vibeplay.db import init_db, insert_track, update_track


def test_update_track(tmp_path: Path) -> None:
    """Verify that update_track correctly modifies an existing track record."""
    db_file = tmp_path / "test_vibeplay.db"
    init_db(db_file)
    conn = sqlite3.connect(db_file)

    # Insert a track initially
    track_id = insert_track(
        conn=conn,
        path="test_file.mp3",
        mtime=123.4,
        size=1000,
        file_hash="hash1",
        duration=120.0,
        bitrate=320,
        title="Old Title",
        artist="Old Artist",
        album_artist="Old Album Artist",
        album="Old Album",
        track_no=1,
        track_total=10,
        disc_no=1,
        disc_total=1,
        year=2020,
        genre="Rock",
        has_cover=False,
        tags_json=json.dumps({"test": "old"}),
    )

    # Modify it and call update_track
    update_track(
        conn=conn,
        track_id=track_id,
        mtime=125.0,
        size=2000,
        file_hash="hash2",
        duration=130.0,
        bitrate=256,
        title="New Title",
        artist="New Artist",
        album_artist="New Album Artist",
        album="New Album",
        track_no=2,
        track_total=12,
        disc_no=2,
        disc_total=2,
        year=2021,
        genre="Pop",
        has_cover=True,
        tags_json=json.dumps({"test": "new"}),
    )

    # Assert updates took effect
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
    row = cursor.fetchone()

    # Map column names to index for assertion readability
    columns = {desc[0]: idx for idx, desc in enumerate(cursor.description)}

    assert row[columns["mtime"]] == 125.0
    assert row[columns["size"]] == 2000
    assert row[columns["hash"]] == "hash2"
    assert row[columns["duration"]] == 130.0
    assert row[columns["bitrate"]] == 256
    assert row[columns["title"]] == "New Title"
    assert row[columns["artist"]] == "New Artist"
    assert row[columns["album_artist"]] == "New Album Artist"
    assert row[columns["album"]] == "New Album"
    assert row[columns["track_no"]] == 2
    assert row[columns["track_total"]] == 12
    assert row[columns["disc_no"]] == 2
    assert row[columns["disc_total"]] == 2
    assert row[columns["year"]] == 2021
    assert row[columns["genre"]] == "Pop"
    assert row[columns["has_cover"]] == 1
    assert row[columns["tags"]] == json.dumps({"test": "new"})
    assert row[columns["status"]] == "active"

    conn.close()
