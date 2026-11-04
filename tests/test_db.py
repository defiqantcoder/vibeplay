import json
from pathlib import Path

from vibeplay.db import (
    TrackRecord,
    add_tracks_to_playlist,
    bulk_update_track_vibe_tags,
    create_playlist,
    delete_playlist,
    get_connection,
    get_existing_tracks,
    get_features_checksum,
    get_playlist,
    get_playlist_tracks,
    get_total_active_tracks_count,
    get_unenriched_tracks,
    init_db,
    insert_or_replace_enrichment,
    insert_or_replace_features,
    insert_track,
    list_playlists,
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
        insert_track(conn=conn, path="/path/3.mp3", mtime=300, size=3000, file_hash="h3")

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


def test_cache_retention_and_cleanup(tmp_path: Path) -> None:
    """Verify TTL expiration, stale entry pruning, and cleanup_expired_caches."""
    from vibeplay.db import (
        cleanup_expired_caches,
        get_cached_response,
        get_llm_cache,
        set_cached_response,
        set_llm_cache,
    )

    db_file = tmp_path / "test_cache.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        # 1. Insert recent and old LLM cache
        set_llm_cache(conn, "recent_llm", "recent prompt", "recent response", "gemini-3.8-flash")
        set_llm_cache(conn, "old_llm", "old prompt", "old response", "gemini-3.8-flash")
        conn.execute("UPDATE llm_cache SET created_at = datetime('now', '-45 days') WHERE prompt_hash = 'old_llm'")

        # 2. Insert recent and old network cache
        set_cached_response(conn, "recent_net", "acoustid", '{"status": "ok"}')
        set_cached_response(conn, "old_net", "acoustid", '{"status": "old"}')
        conn.execute("UPDATE network_cache SET created_at = datetime('now', '-45 days') WHERE cache_key = 'old_net'")

        # 3. Test TTL expiration on get
        assert get_llm_cache(conn, "recent_llm", max_age_days=30) == "recent response"
        assert get_llm_cache(conn, "old_llm", max_age_days=30) is None
        assert get_llm_cache(conn, "old_llm") is None

        assert get_cached_response(conn, "recent_net", max_age_days=30) is not None
        assert get_cached_response(conn, "old_net", max_age_days=30) is None

        # 4. Insert another old record to test batch cleanup_expired_caches
        set_llm_cache(conn, "batch_old_llm", "prompt", "resp", "model")
        conn.execute("UPDATE llm_cache SET created_at = datetime('now', '-45 days') WHERE prompt_hash = 'batch_old_llm'")
        set_cached_response(conn, "batch_old_net", "endpoint", '{"k": "v"}')
        conn.execute("UPDATE network_cache SET created_at = datetime('now', '-45 days') WHERE cache_key = 'batch_old_net'")

        pruned = cleanup_expired_caches(conn, max_age_days=30)
        assert pruned["llm_cache"] >= 1
        assert pruned["network_cache"] >= 1


def test_purge_all_caches(tmp_path: Path) -> None:
    """Verify unconditional purging of LLM and network response caches."""
    from vibeplay.db import purge_all_caches, set_cached_response, set_llm_cache

    db_file = tmp_path / "test_purge.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        set_llm_cache(conn, "h1", "p1", "r1", "m1")
        set_cached_response(conn, "k1", "e1", "r1")

        counts = purge_all_caches(conn)
        assert counts["llm_cache"] == 1
        assert counts["network_cache"] == 1

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM llm_cache")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM network_cache")
        assert cursor.fetchone()[0] == 0


def test_sqlite_concurrency_lock_retry(tmp_path: Path) -> None:
    """Verify that concurrent writes resolve cleanly using exponential backoff retry.

    Multiple worker threads try to write to the same table concurrently,
    forcing `sqlite3.OperationalError` (database is locked).
    The `retry_db_locked` decorator should catch this, wait, and retry until successful.
    """
    import concurrent.futures
    import sqlite3
    import time

    from vibeplay.db import get_connection, init_db, insert_track

    db_file = tmp_path / "test_concurrency.db"
    init_db(db_file)

    num_threads = 10
    tracks_per_thread = 5

    def worker_insert(thread_idx: int) -> int:
        success_count = 0
        with get_connection(db_file, timeout=0.1) as conn:
            for i in range(tracks_per_thread):
                # Small delay to ensure threads overlap
                time.sleep(0.01)
                try:
                    insert_track(
                        conn=conn, path=f"/music/thread{thread_idx}/song{i}.mp3", mtime=1700000000.0, size=5000000, file_hash=f"hash{thread_idx}_{i}"
                    )
                    conn.commit()
                    success_count += 1
                except sqlite3.OperationalError:
                    # We expect the retry decorator to handle "database is locked".
                    # If it leaks out, it means it exhausted max retries or didn't trigger.
                    pass
        return success_count

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_insert, i) for i in range(num_threads)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert sum(results) == num_threads * tracks_per_thread

    # Verify rows in DB
    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tracks")
        count = cursor.fetchone()[0]
        assert count == num_threads * tracks_per_thread


def test_get_total_active_tracks_count(tmp_path: Path):
    db_file = tmp_path / "test_count.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        assert get_total_active_tracks_count(conn) == 0

        id1 = insert_track(conn=conn, path="/path/1.mp3", mtime=100, size=1000, file_hash="h1")
        id2 = insert_track(conn=conn, path="/path/2.mp3", mtime=200, size=2000, file_hash="h2")
        insert_track(conn=conn, path="/path/3.mp3", mtime=300, size=3000, file_hash="h3")

        assert get_total_active_tracks_count(conn) == 3

        mark_tracks_missing(conn, [id1, id2])

        assert get_total_active_tracks_count(conn) == 1


def test_get_features_checksum(tmp_path: Path) -> None:
    """Verify that get_features_checksum generates deterministic SHA-256 hashes (PR #112)."""
    db_file = tmp_path / "test_checksum.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        checksum_empty1 = get_features_checksum(conn)
        checksum_empty2 = get_features_checksum(conn)
        assert checksum_empty1 == checksum_empty2
        assert len(checksum_empty1) == 64

        id1 = insert_track(conn=conn, path="/path/1.mp3", mtime=100, size=1000, file_hash="h1")
        id2 = insert_track(conn=conn, path="/path/2.mp3", mtime=200, size=2000, file_hash="h2")

        insert_or_replace_features(
            conn=conn,
            track_id=id1,
            analyzer_version="1.0",
            bpm=120.0,
            key="C",
            scale="major",
            loudness=-10.5,
            danceability=0.8,
            energy=0.9,
            mood_scores_json='{"happy": 0.9}',
            embedding_blob=b"emb1",
        )

        checksum_1 = get_features_checksum(conn)
        assert checksum_1 != checksum_empty1
        assert checksum_1 == get_features_checksum(conn)

        insert_or_replace_features(
            conn=conn,
            track_id=id2,
            analyzer_version="1.0",
            bpm=130.0,
            key="G",
            scale="minor",
            loudness=-8.5,
            danceability=0.6,
            energy=0.7,
            mood_scores_json='{"sad": 0.8}',
            embedding_blob=b"emb2",
        )

        checksum_2 = get_features_checksum(conn)
        assert checksum_2 != checksum_1
        assert checksum_2 == get_features_checksum(conn)


def test_get_unenriched_tracks_suite(tmp_path: Path) -> None:
    """Verify get_unenriched_tracks behavior (PR #115)."""
    db_file = tmp_path / "test_unenriched.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        id1 = insert_track(conn, path="1.mp3", mtime=1, size=1, file_hash="h1", title="T1")
        id2 = insert_track(conn, path="2.mp3", mtime=1, size=1, file_hash="h2", title="T2")
        id3 = insert_track(conn, path="3.mp3", mtime=1, size=1, file_hash="h3", title="T3")

        insert_or_replace_enrichment(
            conn,
            track_id=id2,
            mb_recording_id=None,
            mb_release_id=None,
            mb_artist_id=None,
            canonical_title="T2",
            canonical_artist=None,
            canonical_album_artist=None,
            canonical_album=None,
            canonical_year=None,
            canonical_track_no=None,
            canonical_track_total=None,
            canonical_disc_no=None,
            canonical_disc_total=None,
            genres=None,
            tags=None,
            confidence=1.0,
            status="matched",
            source="test",
            raw_metadata="{}",
        )

        tracks = get_unenriched_tracks(conn)
        assert len(tracks) == 2
        ids = [t["id"] for t in tracks]
        assert id1 in ids and id3 in ids and id2 not in ids

        # Test force=True
        assert len(get_unenriched_tracks(conn, force=False)) == 2
        assert len(get_unenriched_tracks(conn, force=True)) == 3


def test_delete_playlist(tmp_path: Path) -> None:
    """Verify that deleting a playlist cascades to tracks (PR #122)."""
    db_file = tmp_path / "test_delete_playlist.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        insert_track(conn, "/path/1.mp3", 1.0, 10, "hash1")
        insert_track(conn, "/path/2.mp3", 1.0, 10, "hash2")

        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tracks ORDER BY id")
        track_ids = [row[0] for row in cursor.fetchall()]

        playlist_id = create_playlist(conn, "Test Playlist", "Description", "{}")
        add_tracks_to_playlist(conn, playlist_id, track_ids)

        assert get_playlist(conn, playlist_id) is not None
        assert len(get_playlist_tracks(conn, playlist_id)) == 2

        assert delete_playlist(conn, playlist_id) is True
        assert get_playlist(conn, playlist_id) is None
        assert len(get_playlist_tracks(conn, playlist_id)) == 0
        assert delete_playlist(conn, playlist_id) is False


def test_list_playlists(tmp_path: Path) -> None:
    """Verify list_playlists queries (PR #125)."""
    db_file = tmp_path / "test_list_playlists.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        assert len(list_playlists(conn)) == 0

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tracks (path, mtime, size, hash, status, duration)
            VALUES
                ('/path/to/song1.mp3', 1.0, 100, 'hash1', 'active', 120.0),
                ('/path/to/song2.mp3', 1.0, 100, 'hash2', 'active', 180.0)
        """)
        cursor.execute("""
            INSERT INTO playlists (name, description)
            VALUES
                ('Playlist 1', 'Desc 1'),
                ('Playlist 2', 'Desc 2')
        """)
        cursor.execute("""
            INSERT INTO playlist_tracks (playlist_id, track_id, position)
            VALUES
                (1, 1, 1),
                (1, 2, 2),
                (2, 1, 1)
        """)
        conn.commit()

        playlists = list_playlists(conn)
        assert len(playlists) == 2
        assert playlists[0]["name"] == "Playlist 2"
        assert playlists[0]["track_count"] == 1
        assert playlists[0]["total_duration"] == 120.0


def test_bulk_update_track_vibe_tags(tmp_path: Path) -> None:
    """Verify bulk_update_track_vibe_tags with exact JSON parsing (PR #126 + CodeRabbit)."""
    db_file = tmp_path / "test_bulk_vibe.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        t1 = insert_track(conn, "/path/1.mp3", 1.0, 100, "h1")
        t2 = insert_track(conn, "/path/2.mp3", 1.0, 100, "h2")

        # Test with duplicate track ID to verify deduplication
        updates = [
            (t1, ["initial_mood"], ["initial_genre"]),
            (t1, ["chill", "ambient"], ["electronic"]),
            (t2, ["energetic"], ["rock"]),
        ]
        bulk_update_track_vibe_tags(conn, updates)

        cursor = conn.cursor()
        cursor.execute("SELECT track_id, tags, genres FROM enrichment ORDER BY track_id")
        rows = cursor.fetchall()
        assert len(rows) == 2

        # Verify t1 has the deduplicated last tag values (exact JSON comparison)
        assert rows[0][0] == t1
        assert json.loads(rows[0][1]) == ["chill", "ambient"]
        assert json.loads(rows[0][2]) == ["electronic"]

        assert rows[1][0] == t2
        assert json.loads(rows[1][1]) == ["energetic"]
        assert json.loads(rows[1][2]) == ["rock"]
