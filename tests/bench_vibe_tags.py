import tempfile
import time
from pathlib import Path

from vibeplay.db import get_connection, init_db, update_track_vibe_tags


def setup_db(db_path):
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        tracks = []
        for i in range(1, 1001):
            tracks.append((i, f"path_{i}.mp3", f"hash_{i}", 0, 1000, 100.0, "title", "artist", "active"))

        cursor.executemany(
            """
            INSERT INTO tracks (id, path, hash, mtime, size, duration, title, artist, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tracks,
        )
        enrichments = []
        for i in range(1, 501):
            enrichments.append((i, "source", "[]", "[]", "matched", 1.0))
        cursor.executemany(
            """
            INSERT INTO enrichment (track_id, source, tags, genres, status, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            enrichments,
        )


def run_benchmark():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = Path(tmp.name)
        setup_db(db_path)

        with get_connection(db_path) as conn:
            # Generate dummy data
            records = []
            for i in range(1, 1001):
                records.append((i, ["chill", "focus"], ["ambient", "electronic"]))

            start_time = time.time()
            for record in records:
                update_track_vibe_tags(conn, record[0], record[1], record[2])
            end_time = time.time()

            print(f"Baseline (update_track_vibe_tags): {end_time - start_time:.4f} seconds")


def bench_bulk():
    from vibeplay.db import bulk_update_track_vibe_tags

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = Path(tmp.name)
        setup_db(db_path)

        with get_connection(db_path) as conn:
            # Generate dummy data
            records = []
            for i in range(1, 1001):
                records.append((i, ["chill", "focus"], ["ambient", "electronic"]))

            start_time = time.time()
            bulk_update_track_vibe_tags(conn, records)
            end_time = time.time()

            print(f"Bulk (bulk_update_track_vibe_tags): {end_time - start_time:.4f} seconds")


if __name__ == "__main__":
    run_benchmark()
    bench_bulk()
