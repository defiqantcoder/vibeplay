"""Concurrency and transaction atomicity tests for SQLite immediate transactions."""

import concurrent.futures
import json
import random
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from vibeplay.db import (
    add_tracks_to_playlist,
    bulk_update_track_vibe_tags,
    create_playlist,
    get_connection,
    get_playlist_tracks,
    immediate_transaction,
    init_db,
    insert_track,
    replace_playlist_tracks,
    update_track_vibe_tags,
)


def writer_worker(db_path: Path, track_id: int) -> Exception | None:
    """Simulate a background worker committing writes and then performing bulk immediate-transaction updates."""
    conn = get_connection(db_path)
    try:
        with conn:
            actual_track_id = insert_track(
                conn,
                path=f"/test/path_{track_id}.flac",
                mtime=1234567.0,
                size=1024,
                file_hash=f"hash_{track_id}",
                duration=120.0,
                artist="Artist",
                album="Album",
                title=f"Title {track_id}",
                genre="Genre",
                year=2024,
            )
            update_track_vibe_tags(conn, actual_track_id, ["mood"], ["genre"])

        # Perform a read on a clean connection before bulk_update_track_vibe_tags acquires BEGIN IMMEDIATE
        conn.execute("SELECT tags FROM enrichment WHERE track_id = ?", (actual_track_id,)).fetchone()
        time.sleep(random.uniform(0.01, 0.05))
        bulk_update_track_vibe_tags(conn, [(actual_track_id, ["chill"], ["indie"])])
    except sqlite3.OperationalError as err:
        return err
    finally:
        conn.close()
    return None


def test_db_concurrency_no_deadlocks(tmp_path: Path) -> None:
    """Verify concurrent workers do not deadlock and stored vibe tags match final bulk update."""
    db_path = tmp_path / "test_concurrency.db"
    init_db(db_path)

    num_workers = 10
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(writer_worker, db_path, i) for i in range(1, num_workers + 1)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    for res in results:
        assert res is None, f"Worker encountered an error: {res}"

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT t.id, t.tags AS track_tags, e.tags AS enrich_tags, e.genres AS enrich_genres
            FROM tracks t
            JOIN enrichment e ON e.track_id = t.id
            """
        ).fetchall()
        assert len(rows) == num_workers
        for row in rows:
            assert json.loads(row["track_tags"]) == ["chill"]
            assert json.loads(row["enrich_tags"]) == ["chill"]
            assert json.loads(row["enrich_genres"]) == ["indie"]
    finally:
        conn.close()


def test_read_snapshot_then_concurrent_write_fails_without_immediate_and_succeeds_with_immediate(tmp_path: Path) -> None:
    """Demonstrate that deferred read->write upgrade fails under contention while immediate_transaction succeeds."""
    db_path = tmp_path / "snapshot.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        tid = insert_track(
            conn,
            path="/test/snapshot.flac",
            mtime=1.0,
            size=100,
            file_hash="snap",
            duration=60.0,
        )

    # 1. Naive deferred transaction (BEGIN + SELECT, then another connection commits a write, then upgrade fails)
    c1 = sqlite3.connect(db_path, timeout=0.1)
    c2 = sqlite3.connect(db_path, timeout=0.1)
    try:
        c1.execute("BEGIN")
        c1.execute("SELECT title FROM tracks WHERE id = ?", (tid,)).fetchone()
        c2.execute("BEGIN IMMEDIATE")
        c2.execute("UPDATE tracks SET title = 'From C2' WHERE id = ?", (tid,))
        c2.commit()
        with pytest.raises(sqlite3.OperationalError):
            c1.execute("UPDATE tracks SET title = 'From C1' WHERE id = ?", (tid,))
        c1.rollback()
    finally:
        c1.close()
        c2.close()

    # 2. Using immediate_transaction acquires the write lock upfront, serializing cleanly via busy_timeout
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def immediate_worker(new_title: str) -> None:
        conn = get_connection(db_path, timeout=5.0)
        try:
            barrier.wait(timeout=5.0)
            with immediate_transaction(conn):
                conn.execute("SELECT title FROM tracks WHERE id = ?", (tid,)).fetchone()
                time.sleep(0.03)
                conn.execute("UPDATE tracks SET title = ? WHERE id = ?", (new_title, tid))
        except Exception as err:
            errors.append(err)
        finally:
            conn.close()

    t1 = threading.Thread(target=immediate_worker, args=("Alpha",))
    t2 = threading.Thread(target=immediate_worker, args=("Beta",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == []


def test_immediate_transaction_preserves_outer_atomicity(tmp_path: Path) -> None:
    """Verify immediate_transaction inside an active transaction uses a savepoint rather than committing outer work."""
    db_path = tmp_path / "outer_atomicity.db"
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        tid = insert_track(conn, path="/test/a.flac", mtime=1.0, size=10, file_hash="ha", duration=10.0)
        pid = create_playlist(conn, name="Uncommitted Playlist")
        assert conn.in_transaction is True
        add_tracks_to_playlist(conn, pid, [tid])
        # Roll back the outer transaction; neither playlist nor track should have been committed
        conn.rollback()
    finally:
        conn.close()

    with get_connection(db_path) as check_conn:
        assert check_conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 0
        assert check_conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0] == 0


def test_replace_playlist_tracks_atomicity_on_fk_error(tmp_path: Path) -> None:
    """Verify failed playlist replacement leaves original playlist associations intact."""
    db_path = tmp_path / "replace_atomic.db"
    init_db(db_path)

    with get_connection(db_path) as conn:
        t1 = insert_track(conn, path="/test/t1.flac", mtime=1.0, size=10, file_hash="h1", duration=10.0)
        t2 = insert_track(conn, path="/test/t2.flac", mtime=1.0, size=10, file_hash="h2", duration=10.0)
        pid = create_playlist(conn, name="Safe Playlist")
        add_tracks_to_playlist(conn, pid, [t1, t2])

    with get_connection(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            # 99999 does not exist in tracks -> foreign key failure mid-replace
            replace_playlist_tracks(conn, pid, [t2, 99999])

    with get_connection(db_path) as conn:
        tracks = get_playlist_tracks(conn, pid)
        assert [row["track_id"] for row in tracks] == [t1, t2]
