from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from vibeplay.config import Settings
from vibeplay.db import get_connection
from vibeplay.web import get_filtered_tracks
from vibeplay.player import get_playback_status

router = APIRouter(prefix="/api/library", tags=["library"])


def get_db_path(request: Request) -> Path:
    return request.app.state.db_path


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_templates(request: Request):
    return request.app.state.templates


@router.get("/table", response_class=HTMLResponse)
async def api_library_table(
    request: Request,
    db_path: Annotated[Path, Depends(get_db_path)],
    cfg: Annotated[Settings, Depends(get_settings)],
    templates: Annotated[object, Depends(get_templates)],
    q: str | None = None,
    artist: str | None = None,
    key: str | None = None,
    mood: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    sort: str = "id_asc",
):
    with get_connection(db_path) as conn:
        tracks = get_filtered_tracks(
            conn=conn,
            q=q,
            artist=artist,
            key=key,
            mood=mood,
            bpm_min=bpm_min,
            bpm_max=bpm_max,
            sort=sort,
            mood_threshold=cfg.mood_confidence_threshold,
        )

    playback = get_playback_status(db_path, cfg)
    return templates.TemplateResponse(
        request=request,
        name="components/library_table.html",
        context={
            "tracks": tracks,
            "playback": playback,
            "current_sort": sort,
            "q": q or "",
            "artist": artist or "",
            "key": key or "",
            "mood": mood or "",
            "bpm_min": bpm_min,
            "bpm_max": bpm_max,
        },
    )


@router.post("/rescan")
async def api_library_rescan(
    db_path: Annotated[Path, Depends(get_db_path)],
    cfg: Annotated[Settings, Depends(get_settings)],
):
    from vibeplay.jobs import JobType, get_worker_pool, register_job

    pool = get_worker_pool(db_path)
    job_id = register_job(db_path, JobType.LIBRARY_SCAN)
    pool.submit_job(
        job_id,
        "vibeplay.jobs.tasks:run_library_scan",
        db_path,
        cfg.music_directory,
        True,
        False,
    )
    return {"status": "started", "job_id": job_id}


@router.post("/duplicates")
async def api_library_duplicates(
    db_path: Annotated[Path, Depends(get_db_path)],
):
    from vibeplay.jobs import JobType, get_worker_pool, register_job

    pool = get_worker_pool(db_path)
    job_id = register_job(db_path, JobType.DUPLICATE_SCAN)
    pool.submit_job(job_id, "vibeplay.jobs.tasks:run_duplicate_scan", db_path)
    return {"status": "started", "job_id": job_id}
