"""Background job management, progress tracking, and persistence in SQLite."""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from vibeplay.db import get_connection, init_db

logger = logging.getLogger(__name__)

# Lock for coordinating background threads
_JOB_LOCK = threading.Lock()


_INITIALIZED_DBS: set[str] = set()


def _resolve_conn(
    conn_or_path: sqlite3.Connection | Path | str,
) -> tuple[sqlite3.Connection, bool]:
    """Return an active connection and a boolean indicating if it must be closed."""
    if isinstance(conn_or_path, sqlite3.Connection):
        return conn_or_path, False
    path = Path(conn_or_path) if isinstance(conn_or_path, str) else conn_or_path
    resolved_key = str(path.resolve()) if path.exists() else str(path)
    if resolved_key not in _INITIALIZED_DBS:
        init_db(path)
        _INITIALIZED_DBS.add(resolved_key)
    return get_connection(path), True


def create_job_run(
    conn_or_path: sqlite3.Connection | Path | str,
    job_type: str,
    total_items: int = 0,
) -> str:
    """Create a new job run in status 'running' and return its unique ID."""
    job_id = str(uuid.uuid4())
    conn, should_close = _resolve_conn(conn_or_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO job_runs (id, job_type, total_items, processed_items, status)
                VALUES (?, ?, ?, 0, 'running')
                """,
                (job_id, job_type, total_items),
            )
        return job_id
    finally:
        if should_close:
            conn.close()


def update_job_progress(
    conn_or_path: sqlite3.Connection | Path | str,
    job_id: str,
    processed_items: int,
    current_item_name: str | None = None,
    total_items: int | None = None,
) -> None:
    """Update progress and current item for an active job."""
    conn, should_close = _resolve_conn(conn_or_path)
    try:
        with conn:
            if total_items is not None:
                conn.execute(
                    """
                    UPDATE job_runs
                    SET processed_items = ?,
                        current_item_name = COALESCE(?, current_item_name),
                        total_items = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (processed_items, current_item_name, total_items, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE job_runs
                    SET processed_items = ?,
                        current_item_name = COALESCE(?, current_item_name),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (processed_items, current_item_name, job_id),
                )
    except Exception as err:
        logger.debug("Failed updating job progress for %s: %s", job_id, err)
    finally:
        if should_close:
            conn.close()


def complete_job_run(
    conn_or_path: sqlite3.Connection | Path | str,
    job_id: str,
    total_items: int | None = None,
) -> None:
    """Mark a job as successfully completed."""
    conn, should_close = _resolve_conn(conn_or_path)
    try:
        with conn:
            if total_items is not None:
                conn.execute(
                    """
                    UPDATE job_runs
                    SET status = 'completed',
                        processed_items = ?,
                        total_items = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (total_items, total_items, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE job_runs
                    SET status = 'completed',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (job_id,),
                )
    except Exception as err:
        logger.debug("Failed marking job %s completed: %s", job_id, err)
    finally:
        if should_close:
            conn.close()


def fail_job_run(
    conn_or_path: sqlite3.Connection | Path | str,
    job_id: str,
    error_message: str,
) -> None:
    """Mark a job as failed with an error message."""
    conn, should_close = _resolve_conn(conn_or_path)
    try:
        with conn:
            conn.execute(
                """
                UPDATE job_runs
                SET status = 'failed',
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_message, job_id),
            )
    except Exception as err:
        logger.debug("Failed marking job %s failed: %s", job_id, err)
    finally:
        if should_close:
            conn.close()


def is_job_type_running(conn_or_path: sqlite3.Connection | Path | str, job_type: str) -> bool:
    """Check if any job of the given type is currently running."""
    conn, should_close = _resolve_conn(conn_or_path)
    try:
        cursor = conn.execute(
            "SELECT 1 FROM job_runs WHERE job_type = ? AND status = 'running' LIMIT 1",
            (job_type,),
        )
        return cursor.fetchone() is not None
    except Exception:
        return False
    finally:
        if should_close:
            conn.close()


def get_active_jobs(conn_or_path: sqlite3.Connection | Path | str) -> list[dict[str, Any]]:
    """Return all jobs that are currently running, sorted by creation date."""
    conn, should_close = _resolve_conn(conn_or_path)
    try:
        cursor = conn.execute(
            """
            SELECT id, job_type, total_items, processed_items, current_item_name,
                   status, error_message, created_at, updated_at
            FROM job_runs
            WHERE status = 'running'
            ORDER BY created_at ASC
            """
        )
        rows = cursor.fetchall()
        jobs: list[dict[str, Any]] = []
        for r in rows:
            total = r[2] or 0
            processed = r[3] or 0
            pct = round((processed / total * 100), 1) if total > 0 else 0.0
            jobs.append(
                {
                    "id": r[0],
                    "job_type": r[1],
                    "total_items": total,
                    "processed_items": processed,
                    "percent": pct,
                    "current_item_name": r[4] or "",
                    "status": r[5],
                    "error_message": r[6] or "",
                    "created_at": r[7],
                    "updated_at": r[8],
                }
            )
        return jobs
    except Exception as err:
        logger.debug("Failed fetching active jobs: %s", err)
        return []
    finally:
        if should_close:
            conn.close()


def get_recent_jobs(
    conn_or_path: sqlite3.Connection | Path | str, limit: int = 5
) -> list[dict[str, Any]]:
    """Return recent jobs including completed and failed ones."""
    conn, should_close = _resolve_conn(conn_or_path)
    try:
        cursor = conn.execute(
            """
            SELECT id, job_type, total_items, processed_items, current_item_name,
                   status, error_message, created_at, updated_at
            FROM job_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        jobs: list[dict[str, Any]] = []
        for r in rows:
            total = r[2] or 0
            processed = r[3] or 0
            pct = round((processed / total * 100), 1) if total > 0 else 0.0
            jobs.append(
                {
                    "id": r[0],
                    "job_type": r[1],
                    "total_items": total,
                    "processed_items": processed,
                    "percent": pct,
                    "current_item_name": r[4] or "",
                    "status": r[5],
                    "error_message": r[6] or "",
                    "created_at": r[7],
                    "updated_at": r[8],
                }
            )
        return jobs
    except Exception as err:
        logger.debug("Failed fetching recent jobs: %s", err)
        return []
    finally:
        if should_close:
            conn.close()


# -------------------------------------------------------------------------
# Background Worker Threads
# -------------------------------------------------------------------------

def start_background_scan(db_path: Path, music_dir: Path) -> tuple[str, bool]:
    """Start scanning directory in a background daemon thread.

    Returns:
        tuple[str, bool]: (job_id, was_started). If already running, returns existing job_id and False.
    """
    with _JOB_LOCK:
        if is_job_type_running(db_path, "scan"):
            active = get_active_jobs(db_path)
            for j in active:
                if j["job_type"] == "scan":
                    return j["id"], False
        job_id = create_job_run(db_path, "scan", 0)

    def _worker() -> None:
        try:
            from vibeplay.scanner import scan_directory

            def _cb(curr: int, total: int, file_path: Path) -> None:
                update_job_progress(
                    db_path,
                    job_id,
                    processed_items=curr,
                    current_item_name=file_path.name,
                    total_items=total,
                )

            summary = scan_directory(music_dir, db_path, progress_callback=_cb)
            complete_job_run(db_path, job_id, total_items=summary.total)
            logger.info("Background library scan completed: %s", summary)
        except Exception as exc:
            logger.error("Background library scan failed: %s", exc)
            fail_job_run(db_path, job_id, str(exc))

    t = threading.Thread(target=_worker, name=f"scan-worker-{job_id[:8]}", daemon=True)
    t.start()
    return job_id, True


def start_background_enrich(db_path: Path) -> tuple[str, bool]:
    """Start metadata enrichment in a background daemon thread."""
    with _JOB_LOCK:
        if is_job_type_running(db_path, "enrich"):
            active = get_active_jobs(db_path)
            for j in active:
                if j["job_type"] == "enrich":
                    return j["id"], False
        job_id = create_job_run(db_path, "enrich", 0)

    def _worker() -> None:
        try:
            from vibeplay.enrichment import enrich_tracks

            def _cb(curr: int, total: int, track_name: str) -> None:
                update_job_progress(
                    db_path,
                    job_id,
                    processed_items=curr,
                    current_item_name=track_name,
                    total_items=total,
                )

            summary = enrich_tracks(db_path=db_path, progress_callback=_cb)
            complete_job_run(db_path, job_id, total_items=summary.total)
            logger.info("Background enrichment completed: %s", summary)
        except Exception as exc:
            logger.error("Background enrichment failed: %s", exc)
            fail_job_run(db_path, job_id, str(exc))

    t = threading.Thread(target=_worker, name=f"enrich-worker-{job_id[:8]}", daemon=True)
    t.start()
    return job_id, True


def start_background_analyze(db_path: Path) -> tuple[str, bool]:
    """Start audio feature extraction in a background daemon thread."""
    with _JOB_LOCK:
        if is_job_type_running(db_path, "analyze"):
            active = get_active_jobs(db_path)
            for j in active:
                if j["job_type"] == "analyze":
                    return j["id"], False
        job_id = create_job_run(db_path, "analyze", 0)

    def _worker() -> None:
        try:
            from vibeplay.analysis import analyze_tracks

            def _cb(curr: int, total: int, track_title: str, elapsed: float) -> None:
                update_job_progress(
                    db_path,
                    job_id,
                    processed_items=curr,
                    current_item_name=track_title,
                    total_items=total,
                )

            summary = analyze_tracks(db_path=db_path, progress_callback=_cb)
            complete_job_run(db_path, job_id, total_items=summary.total)
            logger.info("Background analysis completed: %s", summary)
        except Exception as exc:
            logger.error("Background analysis failed: %s", exc)
            fail_job_run(db_path, job_id, str(exc))

    t = threading.Thread(target=_worker, name=f"analyze-worker-{job_id[:8]}", daemon=True)
    t.start()
    return job_id, True
