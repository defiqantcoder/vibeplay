import logging
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from vibeplay.db import get_connection
from vibeplay.player import get_playback_status
from vibeplay.web import get_filtered_tracks

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/library/table", response_class=HTMLResponse)
async def api_library_table(
    request: Request,
    q: str | None = None,
    artist: str | None = None,
    key: str | None = None,
    mood: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    sort: str = "id_asc",
) -> Response:
    """HTMX endpoint returning filtered library table component."""
    with get_connection(request.app.state.db_path) as conn:
        tracks = get_filtered_tracks(
            conn=conn,
            q=q,
            artist=artist,
            key=key,
            mood=mood,
            bpm_min=bpm_min,
            bpm_max=bpm_max,
            sort=sort,
            mood_threshold=request.app.state.cfg.mood_confidence_threshold,
        )

    playback = get_playback_status(request.app.state.db_path, request.app.state.cfg)
    return request.app.state.templates.TemplateResponse(
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


@router.post("/api/library/rescan")
async def api_library_rescan(request: Request) -> JSONResponse:
    """Scan music directory for new audio files."""
    try:
        from vibeplay.scanner import scan_directory

        music_dir = Path("~/Music").expanduser()
        if not music_dir.exists():
            music_dir = Path.cwd()
        stats = scan_directory(music_dir, db_path=request.app.state.db_path)
        return JSONResponse(
            content={
                "status": "success",
                "files_found": stats.files_found,
                "files_added": stats.files_added,
                "files_updated": stats.files_updated,
            }
        )
    except Exception as err:
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/api/library/duplicates")
async def api_library_duplicates(request: Request) -> JSONResponse:
    """Run duplicate track detection via the maintenance plugin."""
    from vibeplay.plugins.maintenance.duplicates import find_duplicate_tracks

    try:
        duplicates = find_duplicate_tracks(request.app.state.db_path)
        return JSONResponse(content={"duplicates": duplicates, "count": len(duplicates)})
    except Exception as err:
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/api/library/scan")
async def api_library_scan(request: Request) -> JSONResponse:
    """Start an asynchronous background scan of a music folder."""
    try:
        from vibeplay.jobs import start_background_scan

        scan_path_str: str | None = None
        ct = request.headers.get("content-type", "")
        if "application/json" in ct:
            try:
                data = await request.json()
                scan_path_str = data.get("path")
            except Exception:
                pass
        elif "application/x-www-form-urlencoded" in ct or "multipart/form-data" in ct:
            form = await request.form()
            scan_path_str = str(form.get("path", "")).strip() or None

        if not scan_path_str:
            music_dir_val = getattr(request.app.state.cfg, "music_dir", None)
            scan_path = Path(music_dir_val).expanduser() if music_dir_val else Path.home() / "Music"
            if not scan_path.exists():
                scan_path = Path.cwd()
        else:
            scan_path = Path(scan_path_str).expanduser().resolve()

        if not scan_path.exists() or not scan_path.is_dir():
            return JSONResponse(
                status_code=400,
                content={"error": f"Path is not a valid directory: {scan_path}"},
            )

        job_id, started = start_background_scan(request.app.state.db_path, scan_path)
        return JSONResponse(
            status_code=202 if started else 200,
            content={
                "job_id": job_id,
                "status": "running" if started else "already_running",
                "path": str(scan_path),
            },
        )
    except Exception as err:
        logger.error("Error initiating library scan: %s", err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/api/library/enrich")
async def api_library_enrich(request: Request) -> JSONResponse:
    """Start asynchronous background metadata enrichment."""
    try:
        from vibeplay.jobs import start_background_enrich

        job_id, started = start_background_enrich(request.app.state.db_path)
        return JSONResponse(
            status_code=202 if started else 200,
            content={
                "job_id": job_id,
                "status": "running" if started else "already_running",
            },
        )
    except Exception as err:
        logger.error("Error initiating metadata enrichment: %s", err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.post("/api/library/analyze")
async def api_library_analyze(request: Request) -> JSONResponse:
    """Start asynchronous background vibe feature analysis."""
    try:
        from vibeplay.jobs import start_background_analyze

        job_id, started = start_background_analyze(request.app.state.db_path)
        return JSONResponse(
            status_code=202 if started else 200,
            content={
                "job_id": job_id,
                "status": "running" if started else "already_running",
            },
        )
    except Exception as err:
        logger.error("Error initiating feature analysis: %s", err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.get("/api/jobs/status")
async def api_jobs_status(request: Request) -> JSONResponse:
    """Return active and recent background jobs status."""
    try:
        from vibeplay.jobs import get_active_jobs, get_recent_jobs

        active = get_active_jobs(request.app.state.db_path)
        recent = get_recent_jobs(request.app.state.db_path, limit=5)
        return JSONResponse(
            content={
                "active_jobs": active,
                "active_count": len(active),
                "recent_jobs": recent,
            }
        )
    except Exception as err:
        logger.error("Error fetching jobs status: %s", err)
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.get("/api/jobs/progress-widget", response_class=HTMLResponse)
async def api_jobs_progress_widget(request: Request) -> Response:
    """Render the live HTMX progress banner micro-component."""
    from vibeplay.jobs import get_active_jobs, get_recent_jobs

    active = get_active_jobs(request.app.state.db_path)
    recent = get_recent_jobs(request.app.state.db_path, limit=3)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="components/job_progress.html",
        context={
            "active_jobs": active,
            "recent_jobs": recent,
            "has_active": len(active) > 0,
        },
    )
