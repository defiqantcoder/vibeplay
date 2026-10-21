from pathlib import Path

from vibeplay.db import init_db, get_connection, get_existing_tracks, TrackRecord


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
