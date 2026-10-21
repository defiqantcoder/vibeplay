"""Tests for database functions."""

import sqlite3
from pathlib import Path


from vibeplay.db import init_db, mark_tracks_missing


def test_mark_tracks_missing(tmp_path: Path) -> None:
    """Verify that mark_tracks_missing correctly updates track status."""
    db_file = tmp_path / "test_vibeplay.db"
    init_db(db_file)

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Insert some active tracks
    cursor.execute(
        """
        INSERT INTO tracks (path, mtime, size, hash, status)
        VALUES
            ('/path/1.mp3', 100, 1000, 'hash1', 'active'),
            ('/path/2.mp3', 200, 2000, 'hash2', 'active'),
            ('/path/3.mp3', 300, 3000, 'hash3', 'active')
        """
    )
    conn.commit()

    # Get IDs
    cursor.execute("SELECT id FROM tracks ORDER BY path")
    track_ids = [row[0] for row in cursor.fetchall()]

    # Mark first two as missing
    updated = mark_tracks_missing(conn, track_ids[:2])

    assert updated == 2

    # Check status
    cursor.execute("SELECT path, status FROM tracks ORDER BY path")
    rows = cursor.fetchall()

    assert rows[0] == ("/path/1.mp3", "missing")
    assert rows[1] == ("/path/2.mp3", "missing")
    assert rows[2] == ("/path/3.mp3", "active")

    # Call again with the same IDs, should return 0 (already missing)
    updated = mark_tracks_missing(conn, track_ids[:2])
    assert updated == 0

    # Call with empty list, should return 0
    updated = mark_tracks_missing(conn, [])
    assert updated == 0

    conn.close()
