"""Audio analysis package for extracting vibe features and embeddings."""

import json
import logging
import signal
import time
from abc import ABC, abstractmethod
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from vibeplay.analysis.base import (
    AudioFeatures,
    BaseAnalyzer,
    decode_audio_slice,
    downmix_to_mono,
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
CancelCheckCallback = Callable[[], bool]


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


_WORKER_ANALYZER: BaseAnalyzer | None = None


def _init_analysis_worker(backend: str, models_dir_str: str | None) -> None:
    """Initializer for process pool workers to load the analyzer once per process."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    global _WORKER_ANALYZER
    models_dir = Path(models_dir_str) if models_dir_str else None
    _WORKER_ANALYZER = get_analyzer(backend=backend, models_dir=models_dir)


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
        global _WORKER_ANALYZER
        if _WORKER_ANALYZER is not None:
            analyzer = _WORKER_ANALYZER
        else:
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


class ExecutionAdapter(ABC):
    """Abstract adapter for executing analysis tasks."""

    @abstractmethod
    def process_batch(
        self,
        batch: list[tuple],
        cancel_check: CancelCheckCallback | None,
    ) -> Iterator[tuple[tuple, Any]]:
        """Process a batch of tasks and yield results as they complete."""
        ...

    def cancel(self) -> None:
        """Cancel ongoing execution if supported."""
        pass

    def shutdown(self) -> None:
        """Shutdown resources."""
        pass


class SequentialExecutionAdapter(ExecutionAdapter):
    """Executes analysis tasks sequentially."""

    def process_batch(
        self,
        batch: list[tuple],
        cancel_check: CancelCheckCallback | None,
    ) -> Iterator[tuple[tuple, Any]]:
        for args in batch:
            if cancel_check and cancel_check():
                break
            try:
                result = _analyze_single_track_task(*args)
                yield args, result
            except Exception as err:
                yield args, err


class ParallelExecutionAdapter(ExecutionAdapter):
    """Executes analysis tasks in parallel using a process pool."""

    def __init__(self, worker_count: int, backend: str, models_dir_str: str | None) -> None:
        """Create a process pool configured with per-worker analyzer initialization."""
        self._cancel_requested = False
        self._futures: set[Future] = set()
        self.executor = ProcessPoolExecutor(
            max_workers=worker_count,
            initializer=_init_analysis_worker,
            initargs=(backend, models_dir_str),
        )

    def process_batch(
        self,
        batch: list[tuple],
        cancel_check: CancelCheckCallback | None,
    ) -> Iterator[tuple[tuple, Any]]:
        """Submit a batch of track tasks and yield ``(args, result_or_err)`` as they finish."""
        futures = {self.executor.submit(_analyze_single_track_task, *args): args for args in batch}
        self._futures = set(futures)
        try:
            for future in as_completed(futures):
                if cancel_check and cancel_check():
                    self.cancel()
                    break
                args = futures[future]
                try:
                    yield args, future.result()
                except Exception as err:
                    yield args, err
        except Exception as e:
            logger.error("Batch processing error: %s", e)

    def cancel(self) -> None:
        """Mark cancellation requested and cancel queued futures without dropping pool join ability."""
        self._cancel_requested = True
        # Keep the executor intact so final shutdown can join dispatched workers.
        for future in self._futures:
            future.cancel()

    def shutdown(self) -> None:
        """Shut down the worker pool, preserving pending cancellation until all workers exit."""
        # Keep cancellation enabled until the pool has drained its pending work.
        self.executor.shutdown(wait=True, cancel_futures=self._cancel_requested)


def analyze_tracks(
    db_path: Path,
    backend: str = "essentia",
    workers: int | None = None,
    force: bool = False,
    limit: int | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheckCallback | None = None,
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
    import os

    if workers is not None:
        worker_count = workers
    else:
        worker_count = min(os.cpu_count() or 4, 8)
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

        batch_size = 16
        completed_count = 0

        # Create execution adapter
        adapter: ExecutionAdapter
        if worker_count > 1:
            adapter = ParallelExecutionAdapter(worker_count, backend, str(settings.models_dir) if settings.models_dir else None)
        else:
            adapter = SequentialExecutionAdapter()

        try:
            for i in range(0, len(task_args), batch_size):
                if cancel_check and cancel_check():
                    logger.info("Analysis job cancelled.")
                    adapter.cancel()
                    break

                batch = task_args[i : i + batch_size]
                batch_results = []

                for args, result_or_err in adapter.process_batch(batch, cancel_check):
                    if isinstance(result_or_err, Exception):
                        summary.failed += 1
                        logger.warning("Task execution error for %s: %s", args[1], result_or_err)
                        continue

                    result = result_or_err
                    completed_count += 1

                    track_name = Path(args[1]).name
                    track_id, features, err_msg, elapsed = result
                    if progress_callback:
                        progress_callback(
                            completed_count,
                            summary.total_considered,
                            track_name,
                            elapsed,
                        )
                    batch_results.append((args, result))

                if cancel_check and cancel_check():
                    logger.info("Analysis job cancelled during batch processing.")
                    break

                # Commit transaction per batch
                with conn:
                    for args, result in batch_results:
                        track_name = Path(args[1]).name
                        track_id, features, err_msg, elapsed = result

                        if features:
                            durations.append(elapsed)
                            summary.analyzed += 1
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
        except KeyboardInterrupt:
            adapter.cancel()
            raise
        finally:
            adapter.shutdown()
    summary.total_seconds = time.perf_counter() - start_total_time
    if durations:
        summary.avg_seconds_per_track = sum(durations) / len(durations)
        # Projected time for the library: (remaining unanalyzed tracks * avg / workers)
        summary.full_library_estimate_seconds = (summary.full_library_tracks * summary.avg_seconds_per_track) / worker_count

    return summary


__all__ = [
    "AnalysisSummary",
    "AudioFeatures",
    "BaseAnalyzer",
    "EssentiaAnalyzer",
    "LibrosaAnalyzer",
    "analyze_tracks",
    "decode_audio_slice",
    "downmix_to_mono",
    "get_analyzer",
    "get_middle_window_offset",
]
