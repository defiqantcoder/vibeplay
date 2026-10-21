import time
from pathlib import Path
import os


def benchmark():
    num_items = 100000
    base_dir = "/media/music/library"
    canonical_library = Path(base_dir)
    canonical_lib_str = str(canonical_library) + os.sep

    # Create dummy existing tracks
    existing_tracks = {}
    for i in range(num_items):
        if i % 2 == 0:
            existing_tracks[f"/media/music/library/Artist/Album/Song{i}.mp3"] = type(
                "Record", (), {"status": "active", "id": i}
            )
        else:
            existing_tracks[f"/media/music/other/Artist/Album/Song{i}.mp3"] = type(
                "Record", (), {"status": "active", "id": i}
            )

    scanned_paths_set = set()  # Assume all are missing for this benchmark

    print("Benchmarking Path instantiation...")
    start_time = time.perf_counter()
    missing_ids = []
    for path_str, record in existing_tracks.items():
        if record.status == "active" and path_str not in scanned_paths_set:
            try:
                p = Path(path_str)
                if p.is_relative_to(canonical_library):
                    missing_ids.append(record.id)
            except ValueError:
                continue
    end_time = time.perf_counter()
    print(f"Path instantiation took {end_time - start_time:.4f} seconds")
    print(f"Found {len(missing_ids)} missing tracks.")

    print("\nBenchmarking string operations...")
    start_time = time.perf_counter()
    missing_ids2 = []
    for path_str, record in existing_tracks.items():
        if record.status == "active" and path_str not in scanned_paths_set:
            if path_str == str(canonical_library) or path_str.startswith(
                canonical_lib_str
            ):
                missing_ids2.append(record.id)
    end_time = time.perf_counter()
    print(f"String operations took {end_time - start_time:.4f} seconds")
    print(f"Found {len(missing_ids2)} missing tracks.")

    assert missing_ids == missing_ids2


benchmark()
