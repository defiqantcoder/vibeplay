from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from vibeplay.config import Settings
from vibeplay.db import get_connection
from vibeplay.player import get_playback_status
from vibeplay.web import get_filtered_tracks

router = APIRouter(prefix="/api/library", tags=["library"])


def extract_cover_bytes(audio_path: Path) -> tuple[bytes, str] | None:
    """Extract embedded or local folder cover art from an audio file."""
    if not audio_path.exists() or not audio_path.is_file():
        return None

    # 1. Try extracting embedded artwork with mutagen
    try:
        import mutagen

        audio = mutagen.File(str(audio_path))
        if audio is not None:
            # FLAC / OGG / Vorbis pictures
            if hasattr(audio, "pictures") and audio.pictures:
                pic = audio.pictures[0]
                return bytes(pic.data), getattr(pic, "mime", "image/jpeg") or "image/jpeg"

            # ID3 / MP3 APIC tags
            if hasattr(audio, "tags") and audio.tags:
                for tag_name in audio.tags.keys():
                    if tag_name.startswith("APIC"):
                        apic = audio.tags[tag_name]
                        return bytes(apic.data), getattr(apic, "mime", "image/jpeg") or "image/jpeg"

                # MP4 / M4A covr
                if "covr" in audio.tags:
                    covr_data = audio.tags["covr"]
                    if covr_data:
                        data = bytes(covr_data[0])
                        mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
                        return data, mime
    except Exception:
        pass

    # 2. Check for folder image in same directory
    try:
        parent_dir = audio_path.parent
        for candidate_name in ["cover.jpg", "cover.png", "folder.jpg", "folder.png", "album.jpg", "front.jpg"]:
            candidate = parent_dir / candidate_name
            if candidate.is_file():
                mime = "image/png" if candidate.suffix.lower() == ".png" else "image/jpeg"
                return candidate.read_bytes(), mime
    except Exception:
        pass

    return None


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


@router.get("/cover/{track_id}")
async def api_library_cover(
    track_id: int,
    db_path: Annotated[Path, Depends(get_db_path)],
    cfg: Annotated[Settings, Depends(get_settings)],
    fallback: bool = False,
):
    """Serve embedded album artwork or return vinyl placeholder / 404."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT path FROM tracks WHERE id = ?", (track_id,))
        row = cursor.fetchone()

    if row and row["path"]:
        from vibeplay.desktop.security import allowed_media_roots, resolve_within

        try:
            safe_path = resolve_within(row["path"], allowed_media_roots(getattr(cfg, "music_dir", None)))
        except (PermissionError, ValueError):
            raise HTTPException(status_code=403, detail="Path traversal attempt detected")
        art = extract_cover_bytes(safe_path)
        if art:
            data, mime = art
            return Response(content=data, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})

    if fallback:
        placeholder_path = Path(__file__).resolve().parent.parent / "static" / "icons" / "vinyl_placeholder.svg"
        if placeholder_path.exists():
            return Response(content=placeholder_path.read_bytes(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    raise HTTPException(status_code=404, detail="Cover art not found")
