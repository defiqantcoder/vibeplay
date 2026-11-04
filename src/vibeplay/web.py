"""Local web UI and API server module using FastAPI, Jinja2, and HTMX."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from vibeplay.config import Settings, get_settings
from vibeplay.db import (
    get_connection,
    get_playlist,
    get_playlist_tracks,
)
from vibeplay.playlist import (
    GeneratedPlaylist,
    PlaylistTrackItem,
    calculate_transition,
    key_to_camelot,
    load_vibe_tracks_and_vectors,
)

logger = logging.getLogger(__name__)


def _format_genre(genre_raw: str | None) -> str:
    """Format genre metadata string or JSON array into clean human-readable text."""
    if not genre_raw:
        return "Lossless Audio"
    genre_raw = genre_raw.strip()
    if genre_raw.startswith("[") and genre_raw.endswith("]"):
        try:
            items = json.loads(genre_raw)
            if isinstance(items, list):
                return ", ".join(i.title() for i in items[:3])
        except Exception:
            pass
    return genre_raw.title()


def get_filtered_tracks(
    conn: Any,
    q: str | None = None,
    artist: str | None = None,
    key: str | None = None,
    mood: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    sort: str = "id_asc",
    mood_threshold: float = 0.50,
) -> list[dict[str, Any]]:
    """Retrieve and filter tracks with features from the SQLite database."""
    query = """
        SELECT
            t.id AS track_id,
            t.path,
            t.duration,
            v.title,
            v.artist,
            v.album,
            v.genre,
            f.bpm,
            f.key,
            f.scale,
            f.energy,
            f.danceability,
            f.loudness,
            f.mood_scores,
            v.mb_recording_id
        FROM tracks t
        LEFT JOIN v_tracks_best_value v ON t.id = v.track_id
        LEFT JOIN features f ON t.id = f.track_id
        WHERE t.status = 'active'
    """
    params: list[Any] = []

    if q and q.strip():
        term = f"%{q.strip()}%"
        query += " AND (v.title LIKE ? OR v.album LIKE ? OR v.artist LIKE ? OR t.path LIKE ?)"
        params.extend([term, term, term, term])

    if artist and artist.strip():
        query += " AND (v.artist = ? OR t.artist = ?)"
        params.extend([artist.strip(), artist.strip()])

    if bpm_min is not None:
        query += " AND f.bpm >= ?"
        params.append(bpm_min)

    if bpm_max is not None:
        query += " AND f.bpm <= ?"
        params.append(bpm_max)

    sort_clause = {
        "title_asc": "ORDER BY LOWER(COALESCE(v.title, t.path)) ASC",
        "title_desc": "ORDER BY LOWER(COALESCE(v.title, t.path)) DESC",
        "artist_asc": "ORDER BY LOWER(COALESCE(v.artist, '')) ASC",
        "artist_desc": "ORDER BY LOWER(COALESCE(v.artist, '')) DESC",
        "album_asc": "ORDER BY LOWER(COALESCE(v.album, '')) ASC",
        "album_desc": "ORDER BY LOWER(COALESCE(v.album, '')) DESC",
        "bpm_asc": "ORDER BY f.bpm ASC",
        "bpm_desc": "ORDER BY f.bpm DESC",
        "harmonic_asc": "ORDER BY f.key ASC, f.scale ASC",
        "harmonic_desc": "ORDER BY f.key DESC, f.scale DESC",
        "key_asc": "ORDER BY f.key ASC, f.scale ASC",
        "key_desc": "ORDER BY f.key DESC, f.scale DESC",
        "energy_asc": "ORDER BY f.energy ASC",
        "energy_desc": "ORDER BY f.energy DESC",
        "danceability_asc": "ORDER BY f.danceability ASC",
        "danceability_desc": "ORDER BY f.danceability DESC",
        "duration_asc": "ORDER BY t.duration ASC",
        "duration_desc": "ORDER BY t.duration DESC",
        "format_asc": "ORDER BY t.bitrate ASC, t.duration ASC",
        "format_desc": "ORDER BY t.bitrate DESC, t.duration DESC",
        "id_asc": "ORDER BY t.id ASC",
        "id_desc": "ORDER BY t.id DESC",
    }.get(sort, "ORDER BY t.id ASC")

    query += f" {sort_clause}"

    cursor = conn.cursor()
    cursor.execute(query, params)
    raw_rows = cursor.fetchall()

    tracks: list[dict[str, Any]] = []
    key_filter = key.strip().upper() if key and key.strip() else None
    mood_filter = mood.strip().lower() if mood and mood.strip() else None

    for r in raw_rows:
        row_dict = dict(r)
        cam = key_to_camelot(row_dict["key"], row_dict["scale"])
        row_dict["camelot"] = cam
        row_dict["title"] = row_dict["title"] or Path(row_dict["path"]).stem
        row_dict["artist"] = row_dict["artist"] or "Unknown Artist"
        row_dict["album"] = row_dict["album"] or "Unknown Album"
        row_dict["duration"] = float(row_dict["duration"]) if row_dict["duration"] else 0.0
        row_dict["genre"] = _format_genre(row_dict["genre"])

        # Filter by key/camelot if requested
        if key_filter:
            track_key = str(row_dict["key"] or "").upper()
            track_cam = str(cam or "").upper()
            if key_filter != track_key and key_filter != track_cam:
                continue

        # Filter by mood if requested
        if mood_filter:
            mood_scores = {}
            if row_dict.get("mood_scores"):
                try:
                    mood_scores = json.loads(row_dict["mood_scores"])
                except Exception:
                    pass

            if mood_filter == "chill":
                if row_dict.get("energy") and float(row_dict["energy"]) > 0.55:
                    continue
                if mood_scores.get("relaxed", 0.0) < 0.30:
                    continue
            elif mood_filter in ("energetic", "workout"):
                if (row_dict.get("energy") and float(row_dict["energy"]) < 0.60) and mood_scores.get("party", 0.0) < 0.35:
                    continue
            elif mood_filter in ("melancholic", "sad", "melancholy"):
                if mood_scores.get("sad", 0.0) < mood_threshold and (row_dict.get("energy") and float(row_dict["energy"]) > 0.60):
                    continue
            elif mood_filter == "euphoric":
                if mood_scores.get("happy", 0.0) < 0.35 and mood_scores.get("party", 0.0) < 0.30:
                    continue
            elif mood_filter in ("focus", "deep_focus", "ambient"):
                if row_dict.get("energy") and float(row_dict["energy"]) > 0.50:
                    continue
            elif mood_filter in ("dark", "dark_intense"):
                if mood_scores.get("aggressive", 0.0) < 0.30 and (row_dict.get("energy") and float(row_dict["energy"]) < 0.60):
                    continue
            elif mood_filter == "lofi":
                bpm = float(row_dict.get("bpm") or 0.0)
                if bpm > 0 and (bpm < 65.0 or bpm > 105.0):
                    continue
            elif mood_filter == "driving":
                bpm = float(row_dict.get("bpm") or 0.0)
                if bpm > 0 and (bpm < 105.0 or bpm > 140.0):
                    continue
            elif mood_scores.get(mood_filter, 0.0) < mood_threshold:
                continue

        tracks.append(row_dict)

    return tracks


def get_library_clusters(db_path: Path, settings: Settings | None = None) -> list[dict[str, Any]]:
    """Return empty clusters list since unsupervised clusters are pruned."""
    return []


def load_saved_playlist(db_path: Path, playlist_id: int) -> GeneratedPlaylist | None:
    """Reconstruct a GeneratedPlaylist container from the database."""
    with get_connection(db_path) as conn:
        pl_row = get_playlist(conn, playlist_id)
        if not pl_row:
            return None
        tracks = get_playlist_tracks(conn, playlist_id)

    if not tracks:
        return None

    items: list[PlaylistTrackItem] = []
    prev_meta: dict[str, Any] | None = None
    prev_vec: np.ndarray | None = None

    try:
        track_ids, vectors, _ = load_vibe_tracks_and_vectors(db_path)
        id_to_vec_idx = {tid: idx for idx, tid in enumerate(track_ids)}
    except Exception:
        vectors = None
        id_to_vec_idx = {}

    for pos, t in enumerate(tracks, start=1):
        meta = dict(t)
        tid = int(t["track_id"])
        vec = vectors[id_to_vec_idx[tid]] if vectors is not None and tid in id_to_vec_idx else None
        trans = calculate_transition(prev_meta, meta, prev_vec, vec) if pos > 1 else None
        items.append(
            PlaylistTrackItem(
                position=pos,
                track_id=tid,
                title=meta.get("title") or "Unknown Title",
                artist=meta.get("artist") or "Unknown Artist",
                album=meta.get("album") or "Unknown Album",
                duration=float(meta.get("duration") or 0.0),
                bpm=meta.get("bpm"),
                key=meta.get("key"),
                scale=meta.get("scale"),
                camelot=key_to_camelot(meta.get("key"), meta.get("scale")),
                energy=meta.get("energy"),
                danceability=meta.get("danceability"),
                path=meta.get("path") or "",
                transition=trans,
            )
        )
        prev_meta = meta
        prev_vec = vec

    scores = [item.transition.total_score for item in items if item.transition]
    avg_score = float(np.mean(scores)) if scores else 1.0
    total_dur = sum(item.duration for item in items)

    return GeneratedPlaylist(
        playlist_id=playlist_id,
        name=pl_row["name"],
        description=pl_row["description"],
        mode="saved",
        tracks=items,
        total_duration=round(total_dur, 2),
        avg_transition_score=round(avg_score, 4),
    )


def create_app(
    db_path: Path | None = None,
    settings: Settings | None = None,
    api_key: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI web application.

    Args:
        db_path: Path to SQLite database file.
        settings: Application settings.
        api_key: Optional secret API key for web API authentication.

    Returns:
        FastAPI: Configured web application instance.
    """
    cfg = settings or get_settings()
    resolved_db_path = db_path or cfg.db_path
    effective_api_key = api_key if api_key is not None else cfg.api_key
    settings_file_path = cfg.get_desktop_settings_path(resolved_db_path)

    from vibeplay.desktop.settings import (
        DesktopSettings,
        load_desktop_settings,
    )

    def _sync_runtime_cfg(ds: DesktopSettings) -> None:
        cfg.analyzer_backend = ds.analyzer_backend
        cfg.analyzer_workers = ds.analyzer_workers
        cfg.analyzer_window_seconds = ds.analyzer_window_seconds
        cfg.analyzer_fallback_enabled = ds.analyzer_fallback_enabled
        cfg.mood_confidence_threshold = ds.mood_confidence_threshold
        if hasattr(ds, "llm_provider") and ds.llm_provider:
            cfg.llm_provider = ds.llm_provider
        if hasattr(ds, "gemini_api_key") and ds.gemini_api_key:
            cfg.gemini_api_key = ds.gemini_api_key
        if hasattr(ds, "gemini_model") and ds.gemini_model:
            cfg.llm_model = ds.gemini_model
        if hasattr(ds, "acoustid_api_key") and ds.acoustid_api_key:
            cfg.acoustid_api_key = ds.acoustid_api_key

    if settings_file_path.exists():
        _sync_runtime_cfg(load_desktop_settings(settings_file_path))

    app = FastAPI(
        title="vibeplay",
        description="Audiophile Precision Audio Analysis, Vibe Clustering & Smart Playlist Server",
        version="0.2.0",
    )

    if effective_api_key:

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            path = request.url.path
            if path.startswith("/static") or path == "/favicon.ico" or path == "/docs" or path == "/openapi.json":
                return await call_next(request)

            header_key = request.headers.get("X-API-Key")
            auth_header = request.headers.get("Authorization", "")
            bearer_key = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else None
            query_key = request.query_params.get("api_key") or request.query_params.get("token")
            cookie_key = request.cookies.get("vibeplay_session_token") or request.cookies.get("vibeplay_api_key")

            provided_key = header_key or bearer_key or query_key or cookie_key

            if provided_key != effective_api_key:
                if "text/html" in request.headers.get("accept", ""):
                    return HTMLResponse(
                        content=(
                            "<!DOCTYPE html><html><head><title>401 Unauthorized</title></head>"
                            "<body style='font-family:sans-serif; text-align:center; padding:5rem; background:#111; color:#eee;'>"
                            "<h1>401 Unauthorized</h1><p>A valid API key is required to access the vibeplay console.</p>"
                            "<p style='color:#888;'>Provide ?api_key=&lt;key&gt; or 'X-API-Key' header.</p></body></html>"
                        ),
                        status_code=401,
                    )
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "Unauthorized: Invalid or missing API key. Provide via X-API-Key header, Authorization Bearer token, or ?api_key="
                    },
                )

            response = await call_next(request)
            if query_key == effective_api_key:
                response.set_cookie("vibeplay_session_token", effective_api_key, httponly=True, samesite="lax")
                response.set_cookie("vibeplay_api_key", effective_api_key, httponly=True, samesite="lax")
            return response

    from vibeplay.desktop.packaging import resolve_static_dir, resolve_templates_dir

    static_dir = resolve_static_dir()
    templates_dir = resolve_templates_dir()

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates = Jinja2Templates(directory=str(templates_dir))

    app.state.db_path = resolved_db_path
    app.state.cfg = cfg
    app.state.templates = templates
    app.state.api_key = effective_api_key
    app.state._last_telemetry_snapshot = None

    from vibeplay.routers.desktop import router as desktop_router
    from vibeplay.routers.library import router as library_router
    from vibeplay.routers.player import router as player_router
    from vibeplay.routers.playlist import router as playlist_router
    from vibeplay.routers.plugins import router as plugins_router
    from vibeplay.routers.root import router as root_router
    from vibeplay.routers.settings import router as settings_router

    app.include_router(library_router)
    app.include_router(player_router)
    app.include_router(playlist_router)
    app.include_router(desktop_router)
    app.include_router(settings_router)
    app.include_router(plugins_router)
    app.include_router(root_router)

    from vibeplay.plugins.manager import get_plugin_manager

    plugin_mgr = get_plugin_manager(app)
    plugin_mgr.initialize()
    app.state.plugin_manager = plugin_mgr

    return app


def run_server(
    db_path: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    api_key: str | None = None,
    allow_insecure_remote: bool = False,
    settings: Settings | None = None,
) -> None:
    """Start the local vibeplay web server with security guardrails.

    Enforces loopback-only binding unless an API key is configured or remote access
    is explicitly permitted.

    Args:
        db_path: Path to the SQLite database.
        host: Host address to bind to (defaults to 127.0.0.1).
        port: Port number to bind to (defaults to 8000).
        api_key: Optional secret API key for web API authentication.
        allow_insecure_remote: If True, permit non-localhost bind without an API key.
        settings: Application settings.

    Raises:
        ValueError: If attempting to bind to an external interface without authentication or explicit override.
    """
    cfg = settings or get_settings()
    effective_api_key = api_key if api_key is not None else cfg.api_key
    permit_remote = allow_insecure_remote or cfg.allow_insecure_remote

    from vibeplay.desktop.security import is_loopback_host

    is_loopback = is_loopback_host(host)

    if not is_loopback and not effective_api_key and not permit_remote:
        raise ValueError(
            f"Security Guardrail: Refusing to bind unauthenticated server to external interface '{host}'. "
            "To permit remote access, set an API key (via --api-key / VIBEPLAY_API_KEY) or explicitly pass --allow-insecure-remote."
        )

    logger.info(
        "Starting web server at http://%s:%d with database %s (auth: %s)",
        host,
        port,
        db_path,
        "enabled" if effective_api_key else "disabled (localhost loopback)",
    )
    app = create_app(db_path=db_path, settings=cfg, api_key=effective_api_key)
    uvicorn.run(app, host=host, port=port)
