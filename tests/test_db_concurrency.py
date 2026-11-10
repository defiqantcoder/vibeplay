import concurrent.futures
import sqlite3
import time
import random
from pathlib import Path

import pytest
from vibeplay.db import (
    get_connection,
    init_db,
    insert_track,
    update_track_vibe_tags,
    bulk_update_track_vibe_tags,
)

def writer_worker(db_path: Path, track_id: int):
    """Simulates a background worker doing writes."""
    conn = get_connection(db_path)
    try:
        # 1. Insert a track
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
        # 2. Update tags
        update_track_vibe_tags(conn, actual_track_id, ["mood"], ["genre"])

        # 3. Random small delay to increase chance of overlap
        time.sleep(random.uniform(0.01, 0.05))

        # 4. Bulk update
        bulk_update_track_vibe_tags(conn, [(actual_track_id, ["chill"], ["indie"])])
    except sqlite3.OperationalError as e:
        return e
    finally:
        conn.close()
    return None

def test_db_concurrency_no_deadlocks(tmp_path: Path):
    """Test that multiple concurrent workers doing writes do not deadlock from lock upgrades."""
    db_path = tmp_path / "test_concurrency.db"
    init_db(db_path)

    num_workers = 10
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(writer_worker, db_path, i) for i in range(1, num_workers + 1)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # Check that no worker encountered a database locked error
    for res in results:
        assert res is None, f"Worker encountered an error: {res}"

    # Verify the final state
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tracks")
        count = cursor.fetchone()[0]
        assert count == num_workers
    finally:
        conn.close()
