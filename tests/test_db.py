import sqlite3

import pytest

from vibeplay.db import insert_track, migrate_db


@pytest.fixture
def db_connection():
    """Fixture providing an in-memory database connection with schema migrated."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate_db(conn)
    yield conn
    conn.close()


def test_insert_track(db_connection):
    """Verify that insert_track correctly adds a record into the tracks table."""
    conn = db_connection

    # Test data representing a typical track
    path = "/music/album/song.mp3"
    mtime = 1700000000.0
    size = 5000000
    file_hash = "abcdef123456"
    duration = 240.5
    bitrate = 320000
    title = "Test Song"
    artist = "Test Artist"
    album_artist = "Test Album Artist"
    album = "Test Album"
    track_no = 1
    track_total = 12
    disc_no = 1
    disc_total = 1
    year = 2024
    genre = "Electronic"
    has_cover = True
    tags_json = '{"key": "value"}'

    track_id = insert_track(
        conn=conn,
        path=path,
        mtime=mtime,
        size=size,
        file_hash=file_hash,
        duration=duration,
        bitrate=bitrate,
        title=title,
        artist=artist,
        album_artist=album_artist,
        album=album,
        track_no=track_no,
        track_total=track_total,
        disc_no=disc_no,
        disc_total=disc_total,
        year=year,
        genre=genre,
        has_cover=has_cover,
        tags_json=tags_json,
    )

    # Validate insertion
    assert track_id > 0

    # Query back to ensure data matches
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
    row = cursor.fetchone()

    assert row is not None
    assert row["path"] == path
    assert row["mtime"] == mtime
    assert row["size"] == size
    assert row["hash"] == file_hash
    assert row["duration"] == duration
    assert row["bitrate"] == bitrate
    assert row["title"] == title
    assert row["artist"] == artist
    assert row["album_artist"] == album_artist
    assert row["album"] == album
    assert row["track_no"] == track_no
    assert row["track_total"] == track_total
    assert row["disc_no"] == disc_no
    assert row["disc_total"] == disc_total
    assert row["year"] == year
    assert row["genre"] == genre
    assert row["has_cover"] == 1
    assert row["tags"] == tags_json
    assert row["status"] == "active"
