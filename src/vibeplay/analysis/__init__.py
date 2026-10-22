"""Audio analysis package for extracting vibe features and embeddings."""

import json
import logging

import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from vibeplay.analysis.base import (
    AudioFeatures,
    BaseAnalyzer,
    decode_audio_slice,
    get_middle_window_offset,
)
from vibeplay.analysis.essentia_analyzer import EssentiaAnalyzer
from vibeplay.analysis.librosa_analyzer import LibrosaAnalyzer
from vibeplay.config import get_settings
from vibeplay.db import (
    get_connection,
    get_total_active_tracks_count,
    get_unanalyzed_tracks,
    init_db,
    insert_or_replace_features,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str, float], None]


@dataclass
class AnalysisSummary:
    """Summary and timing metrics for an audio analysis run."""

    total_considered: int = 0
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    total_seconds: float = 0.0
    avg_seconds_per_track: float = 0.0
    full_library_tracks: int = 0
    full_library_estimate_seconds: float = 0.0


def get_analyzer(
    backend: str = "essentia",
    models_dir: Path | None = None,
) -> BaseAnalyzer:
    """Factory creating an audio analyzer with automatic fallback to Librosa.

    Args:
        backend: Preferred analyzer backend ('essentia' or 'librosa').
        models_dir: Optional path to models directory.

    Returns:
        BaseAnalyzer: Instantiated analyzer.
    """
    if backend.lower() == "essentia":
        try:
            return EssentiaAnalyzer(models_dir=models_dir)
        except Exception as err:
            logger.warning(
                "Failed to initialize EssentiaAnalyzer (%s). Falling back to LibrosaAnalyzer.",
                err,
            )
            return LibrosaAnalyzer()
    return LibrosaAnalyzer()


def _analyze_single_track_task(
    track_id: int,
    path_str: str,
    duration: float,
    backend: str,
    models_dir_str: str | None,
    window_seconds: float = 60.0,
) -> tuple[int, AudioFeatures | None, str | None, float]:
    """Worker task function for parallel audio analysis.

    Args:
        track_id: Database track ID.
        path_str: Audio file path string.
        duration: Track duration in seconds.
        backend: Analyzer backend name.
        models_dir_str: Models directory path string.
        window_seconds: Analysis window length.

    Returns:
        tuple: (track_id, features, error_msg, elapsed_seconds)
    """
    start_time = time.perf_counter()
    track_path = Path(path_str)
    try:
        models_dir = Path(models_dir_str) if models_dir_str else None
        analyzer = get_analyzer(backend=backend, models_dir=models_dir)
        features = analyzer.analyze_track(
            path=track_path,
            track_id=track_id,
            duration=duration,
            window_seconds=window_seconds,
        )
        elapsed = time.perf_counter() - start_time
        return track_id, features, None, elapsed
    except Exception as err:
        elapsed = time.perf_counter() - start_time
        return track_id, None, str(err), elapsed


def analyze_tracks(
    db_path: Path,
    backend: str = "essentia",
    workers: int | None = None,
    force: bool = False,
    limit: int | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AnalysisSummary:
    """Analyze audio files in the database using parallel workers.

    Resumable: skips tracks already analyzed with current analyzer version.

    Args:
        db_path: Path to the SQLite database.
        backend: Preferred analyzer ('essentia' or 'librosa').
        workers: Parallel worker count (defaults to CPU count - 1).
        force: If True, re-analyze tracks with existing records.
        limit: Optional maximum tracks to analyze.
        progress_callback: Optional progress hook (current, total, track_title, elapsed).

    Returns:
        AnalysisSummary: Execution counts, average time per track, and library estimate.
    """
    settings = get_settings()
    init_db(db_path)

    analyzer = get_analyzer(backend=backend, models_dir=settings.models_dir)
    target_version = analyzer.version
    worker_count = workers if workers is not None else settings.analyzer_workers
    worker_count = max(1, worker_count)

    summary = AnalysisSummary()
    start_total_time = time.perf_counter()

    with get_connection(db_path) as conn:
        tracks_to_analyze = get_unanalyzed_tracks(
            conn=conn,
            analyzer_version=target_version,
            force=force,
            limit=limit,
        )
        summary.full_library_tracks = get_total_active_tracks_count(conn)
        summary.total_considered = len(tracks_to_analyze)

        if not tracks_to_analyze:
            summary.total_seconds = time.perf_counter() - start_total_time
            return summary

        task_args = [
            (
                row["id"],
                row["path"],
                float(row["duration"] or 0.0),
                backend,
                str(settings.models_dir),
                settings.analyzer_window_seconds,
            )
            for row in tracks_to_analyze
        ]

        durations: list[float] = []

        if worker_count <= 1:
            for idx, args in enumerate(task_args):
                track_id, features, err_msg, elapsed = _analyze_single_track_task(*args)
                track_name = Path(args[1]).name
                if progress_callback:
                    progress_callback(
                        idx + 1, summary.total_considered, track_name, elapsed
                    )

                if features:
                    durations.append(elapsed)
                    summary.analyzed += 1
                    with conn:
                        insert_or_replace_features(
                            conn=conn,
                            track_id=features.track_id,
                            analyzer_version=features.analyzer_version,
                            bpm=features.bpm,
                            key=features.key,
                            scale=features.scale,
                            loudness=features.loudness,
                            danceability=features.danceability,
                            energy=features.energy,
                            mood_scores_json=json.dumps(features.mood_scores),
                            embedding_blob=features.embedding_bytes(),
                        )
                else:
                    summary.failed += 1
                    logger.warning("Failed analyzing track %s: %s", args[1], err_msg)
        else:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(_analyze_single_track_task, *args): args
                    for args in task_args
                }
                completed_count = 0
                for future in as_completed(futures):
                    completed_count += 1
                    args = futures[future]
                    track_name = Path(args[1]).name
                    try:
                        track_id, features, err_msg, elapsed = future.result()
                        if progress_callback:
                            progress_callback(
                                completed_count,
                                summary.total_considered,
                                track_name,
                                elapsed,
                            )

                        if features:
                            durations.append(elapsed)
                            summary.analyzed += 1
                            with conn:
                                insert_or_replace_features(
                                    conn=conn,
                                    track_id=features.track_id,
                                    analyzer_version=features.analyzer_version,
                                    bpm=features.bpm,
                                    key=features.key,
                                    scale=features.scale,
                                    loudness=features.loudness,
                                    danceability=features.danceability,
                                    energy=features.energy,
                                    mood_scores_json=json.dumps(features.mood_scores),
                                    embedding_blob=features.embedding_bytes(),
                                )
                        else:
                            summary.failed += 1
                            logger.warning(
                                "Failed analyzing track %s: %s", args[1], err_msg
                            )
                    except Exception as err:
                        summary.failed += 1
                        logger.warning("Task execution error for %s: %s", args[1], err)

    summary.total_seconds = time.perf_counter() - start_total_time
    if durations:
        summary.avg_seconds_per_track = sum(durations) / len(durations)
        # Projected time for the library: (remaining unanalyzed tracks * avg / workers)
        summary.full_library_estimate_seconds = (
            summary.full_library_tracks * summary.avg_seconds_per_track
        ) / worker_count

    return summary


__all__ = [
    "AnalysisSummary",
    "AudioFeatures",
    "BaseAnalyzer",
    "EssentiaAnalyzer",
    "LibrosaAnalyzer",
    "analyze_tracks",
    "decode_audio_slice",
    "get_analyzer",
    "get_middle_window_offset",
]
