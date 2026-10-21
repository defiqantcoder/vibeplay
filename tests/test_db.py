from pathlib import Path

from vibeplay.db import (
    TrackRecord,
    get_connection,
    get_existing_tracks,
    init_db,
    insert_track,
    mark_tracks_missing,
    update_track,
)


def test_get_existing_tracks(tmp_path: Path):
    db_file = tmp_path / "test.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tracks (
                path, mtime, size, hash, status, title, artist
            ) VALUES (
                '/path/to/song.mp3', 123456789.0, 1024, 'dummyhash', 'active', 'Song Title', 'Artist Name'
            )
        """)
        conn.commit()

        tracks = get_existing_tracks(conn)

        assert isinstance(tracks, dict)
        assert len(tracks) == 1
        assert "/path/to/song.mp3" in tracks

        track = tracks["/path/to/song.mp3"]
        assert isinstance(track, TrackRecord)
        assert track.path == "/path/to/song.mp3"
        assert track.mtime == 123456789.0
        assert track.size == 1024
        assert track.hash == "dummyhash"
        assert track.status == "active"
        assert track.title == "Song Title"
        assert track.artist == "Artist Name"


def test_get_existing_tracks_empty(tmp_path: Path):
    db_file = tmp_path / "test.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        tracks = get_existing_tracks(conn)

        assert isinstance(tracks, dict)
        assert len(tracks) == 0


def test_insert_track(tmp_path: Path):
    """Verify that insert_track correctly adds a record into the tracks table."""
    db_file = tmp_path / "test_insert.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        track_id = insert_track(
            conn=conn,
            path="/music/album/song.mp3",
            mtime=1700000000.0,
            size=5000000,
            file_hash="abcdef123456",
            duration=240.5,
            bitrate=320000,
            title="Test Song",
            artist="Test Artist",
            album_artist="Test Album Artist",
            album="Test Album",
            track_no=1,
            track_total=12,
            disc_no=1,
            disc_total=1,
            year=2024,
            genre="Electronic",
            has_cover=True,
            tags_json='{"key": "value"}',
        )

        assert track_id > 0

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
        row = cursor.fetchone()

        assert row is not None
        assert row["path"] == "/music/album/song.mp3"
        assert row["mtime"] == 1700000000.0
        assert row["size"] == 5000000
        assert row["hash"] == "abcdef123456"
        assert row["duration"] == 240.5
        assert row["bitrate"] == 320000
        assert row["title"] == "Test Song"
        assert row["artist"] == "Test Artist"
        assert row["album_artist"] == "Test Album Artist"
        assert row["album"] == "Test Album"
        assert row["track_no"] == 1
        assert row["track_total"] == 12
        assert row["disc_no"] == 1
        assert row["disc_total"] == 1
        assert row["year"] == 2024
        assert row["genre"] == "Electronic"
        assert row["has_cover"] == 1
        assert row["tags"] == '{"key": "value"}'
        assert row["status"] == "active"


def test_update_track(tmp_path: Path) -> None:
    """Verify that update_track correctly modifies an existing track record."""
    import json
    db_file = tmp_path / "test_update.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        track_id = insert_track(
            conn=conn,
            path="test_file.mp3",
            mtime=123.4,
            size=1000,
            file_hash="hash1",
            title="Old Title",
            artist="Old Artist",
        )

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

        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
        row = cursor.fetchone()

        assert row["mtime"] == 125.0
        assert row["size"] == 2000
        assert row["hash"] == "hash2"
        assert row["duration"] == 130.0
        assert row["bitrate"] == 256
        assert row["title"] == "New Title"
        assert row["artist"] == "New Artist"
        assert row["album_artist"] == "New Album Artist"
        assert row["album"] == "New Album"
        assert row["track_no"] == 2
        assert row["track_total"] == 12
        assert row["year"] == 2021
        assert row["genre"] == "Pop"
        assert row["has_cover"] == 1
        assert row["status"] == "active"


def test_mark_tracks_missing(tmp_path: Path) -> None:
    """Verify that mark_tracks_missing correctly updates track status."""
    db_file = tmp_path / "test_missing.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        id1 = insert_track(conn=conn, path="/path/1.mp3", mtime=100, size=1000, file_hash="h1")
        id2 = insert_track(conn=conn, path="/path/2.mp3", mtime=200, size=2000, file_hash="h2")
        id3 = insert_track(conn=conn, path="/path/3.mp3", mtime=300, size=3000, file_hash="h3")

        updated = mark_tracks_missing(conn, [id1, id2])
        assert updated == 2

        cursor = conn.cursor()
        cursor.execute("SELECT path, status FROM tracks ORDER BY path")
        rows = cursor.fetchall()

        assert rows[0]["status"] == "missing"
        assert rows[1]["status"] == "missing"
        assert rows[2]["status"] == "active"

        # Calling again with same IDs should update 0
        assert mark_tracks_missing(conn, [id1, id2]) == 0
        # Calling with empty list should update 0
        assert mark_tracks_missing(conn, []) == 0

