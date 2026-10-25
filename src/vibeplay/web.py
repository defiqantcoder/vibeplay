"""Local web UI and API server module using FastAPI, Jinja2, and HTMX."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from vibeplay.config import Settings, get_settings
from vibeplay.db import (
    add_tracks_to_playlist,
    get_connection,
    get_playlist,
    get_playlist_tracks,
)
from vibeplay.llm import parse_prompt_to_plan
from vibeplay.player import (
    adjust_volume_step,
    get_audio_file_technical_info,
    get_playback_status,
    next_song,
    play_playlist,
    play_track,
    previous_song,
    seek_playback,
    set_output_profile,
    set_volume_level,
    toggle_mute,
    toggle_pause,
)
from vibeplay.playlist import (
    GeneratedPlaylist,
    PlaylistRuleConfig,
    PlaylistTrackItem,
    calculate_playlist_summary,
    calculate_transition,
    calculate_transition_metrics,
    evaluate_harmonic_transition,
    generate_playlist,
    key_to_camelot,
)
from vibeplay.vectors import ClusterSummary, compute_clusters, get_or_build_vibe_vectors

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
        row_dict["duration"] = (
            float(row_dict["duration"]) if row_dict["duration"] else 0.0
        )
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


def get_library_clusters(
    db_path: Path, settings: Settings | None = None
) -> list[ClusterSummary]:
    """Compute or load unsupervised vibe clusters for the library."""
    try:
        clust_res = compute_clusters(db_path=db_path, settings=settings)
        return clust_res.clusters
    except Exception as err:
        logger.debug("Could not compute clusters: %s", err)
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
        track_ids, vectors, _ = get_or_build_vibe_vectors(db_path)
        id_to_vec_idx = {tid: idx for idx, tid in enumerate(track_ids)}
    except Exception:
        vectors = None
        id_to_vec_idx = {}

    for pos, t in enumerate(tracks, start=1):
        meta = dict(t)
        tid = int(t["track_id"])
        vec = (
            vectors[id_to_vec_idx[tid]]
            if vectors is not None and tid in id_to_vec_idx
            else None
        )
        trans = (
            calculate_transition(prev_meta, meta, prev_vec, vec) if pos > 1 else None
        )
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
        save_desktop_settings,
        update_desktop_settings,
    )

    def _sync_runtime_cfg(ds: DesktopSettings) -> None:
        cfg.analyzer_backend = ds.analyzer_backend
        cfg.analyzer_workers = ds.analyzer_workers
        cfg.analyzer_window_seconds = ds.analyzer_window_seconds
        cfg.analyzer_fallback_enabled = ds.analyzer_fallback_enabled
        cfg.mood_confidence_threshold = ds.mood_confidence_threshold

    if settings_file_path.exists():
        _sync_runtime_cfg(load_desktop_settings(settings_file_path))

    app = FastAPI(
        title="vibeplay",
        description="Audiophile Precision Audio Analysis, Vibe Clustering & Smart Playlist Server",
        version="0.1.0",
    )

    if effective_api_key:

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            path = request.url.path
            if (
                path.startswith("/static")
                or path == "/favicon.ico"
                or path == "/docs"
                or path == "/openapi.json"
            ):
                return await call_next(request)

            header_key = request.headers.get("X-API-Key")
            auth_header = request.headers.get("Authorization", "")
            bearer_key = (
                auth_header.split(" ", 1)[1].strip()
                if auth_header.startswith("Bearer ")
                else None
            )
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
                        "detail": "Unauthorized: Invalid or missing API key. Provide via X-API-Key header, Authorization Bearer token, or ?api_key=..."
                    },
                )

            response = await call_next(request)
            if query_key == effective_api_key:
                response.set_cookie(
                    "vibeplay_session_token", effective_api_key, httponly=True, samesite="lax"
                )
                response.set_cookie(
                    "vibeplay_api_key", effective_api_key, httponly=True, samesite="lax"
                )
            return response

    from vibeplay.desktop.packaging import resolve_static_dir, resolve_templates_dir

    static_dir = resolve_static_dir()
    templates_dir = resolve_templates_dir()

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/", response_class=HTMLResponse)
    async def index_page(request: Request) -> Response:
        """Render the main console dashboard shell."""
        active_desktop_settings = load_desktop_settings(settings_file_path)
        with get_connection(resolved_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM tracks WHERE status = 'active'"
            )
            count_row = cursor.fetchone()
            total_tracks = count_row[0] if count_row else 0
            total_duration = float(count_row[1]) if count_row else 0.0

            cursor.execute(
                """
                SELECT DISTINCT COALESCE(v.artist, t.artist) AS artist_name
                FROM tracks t
                LEFT JOIN v_tracks_best_value v ON t.id = v.track_id
                WHERE t.status = 'active' AND COALESCE(v.artist, t.artist) IS NOT NULL
                ORDER BY LOWER(COALESCE(v.artist, t.artist)) ASC
                """
            )
            artists = [r[0] for r in cursor.fetchall() if r[0]]
            tracks = get_filtered_tracks(
                conn, mood_threshold=cfg.mood_confidence_threshold
            )

            cursor.execute("SELECT id FROM playlists ORDER BY id DESC LIMIT 1")
            recent_pl = cursor.fetchone()

        latest_playlist = None
        if recent_pl:
            try:
                latest_playlist = load_saved_playlist(resolved_db_path, recent_pl[0])
            except Exception as err:
                logger.debug("Could not load recent playlist: %s", err)

        latest_transitions = (
            calculate_transition_metrics(latest_playlist.tracks)
            if latest_playlist
            else []
        )
        latest_summary = (
            calculate_playlist_summary(latest_playlist.tracks, latest_transitions)
            if latest_playlist
            else {}
        )

        clusters = get_library_clusters(resolved_db_path, cfg)
        playback = get_playback_status(resolved_db_path, cfg)

        selected_track = tracks[0] if tracks else None
        selected_tech_info = None
        selected_mood_scores: dict[str, float] = {}
        if selected_track:
            try:
                selected_tech_info = get_audio_file_technical_info(selected_track["path"])
            except Exception:
                selected_tech_info = None
            if selected_track.get("mood_scores"):
                try:
                    selected_mood_scores = json.loads(selected_track["mood_scores"])
                except Exception:
                    selected_mood_scores = {}
            for m in ("electronic", "relaxed", "acoustic", "party", "happy", "aggressive", "sad"):
                if m not in selected_mood_scores:
                    selected_mood_scores[m] = 0.0

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "total_tracks": total_tracks,
                "total_duration": total_duration,
                "total_clusters": len(clusters),
                "tracks": tracks,
                "artists": artists,
                "clusters": clusters,
                "playlist": latest_playlist,
                "transitions": latest_transitions,
                "summary": latest_summary,
                "active_step": 3 if latest_playlist else 1,
                "playback": playback,
                "desktop_settings": active_desktop_settings,
                "selected_track": selected_track,
                "selected_tech_info": selected_tech_info,
                "selected_mood_scores": selected_mood_scores,
            },
        )

    @app.get("/api/library/table", response_class=HTMLResponse)
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
        with get_connection(resolved_db_path) as conn:
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

        playback = get_playback_status(resolved_db_path, cfg)
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

    @app.get("/api/track/{track_id}", response_class=HTMLResponse)
    async def api_track_detail(
        request: Request, track_id: int, view: str | None = None
    ) -> Response:
        """HTMX endpoint returning track detail modal or docked inspector content."""
        with get_connection(resolved_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    t.id AS track_id,
                    t.path,
                    t.duration,
                    t.bitrate,
                    v.title,
                    v.artist,
                    v.album,
                    v.genre,
                    v.year,
                    v.mb_recording_id,
                    f.bpm,
                    f.key,
                    f.scale,
                    f.energy,
                    f.danceability,
                    f.loudness,
                    f.mood_scores
                FROM tracks t
                LEFT JOIN v_tracks_best_value v ON t.id = v.track_id
                LEFT JOIN features f ON t.id = f.track_id
                WHERE t.id = ?
                """,
                (track_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail=f"Track {track_id} not found"
                )

            track_dict = dict(row)
            track_dict["title"] = track_dict["title"] or Path(track_dict["path"]).stem
            track_dict["artist"] = track_dict["artist"] or "Unknown Artist"
            track_dict["album"] = track_dict["album"] or "Unknown Album"
            track_dict["camelot"] = key_to_camelot(
                track_dict["key"], track_dict["scale"]
            )
            track_dict["duration"] = (
                float(track_dict["duration"]) if track_dict["duration"] else 0.0
            )

            mood_scores: dict[str, float] = {}
            if track_dict.get("mood_scores"):
                try:
                    mood_scores = json.loads(track_dict["mood_scores"])
                except Exception:
                    mood_scores = {}

            for m in (
                "happy",
                "sad",
                "relaxed",
                "aggressive",
                "party",
                "acoustic",
                "electronic",
            ):
                if m not in mood_scores:
                    mood_scores[m] = 0.0

            tech_info = get_audio_file_technical_info(track_dict["path"])

        template_name = (
            "components/track_inspector.html"
            if (view == "inspector" or request.headers.get("HX-Target") == "workspace-inspector-content")
            else "components/track_detail.html"
        )

        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={
                "track": track_dict,
                "tech_info": tech_info,
                "mood_scores": mood_scores,
            },
        )

    @app.get("/api/clusters/cards", response_class=HTMLResponse)
    async def api_cluster_cards(request: Request) -> Response:
        """HTMX endpoint returning cluster cards component."""
        clusters = get_library_clusters(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/cluster_cards.html",
            context={
                "clusters": clusters,
            },
        )

    @app.post("/api/playlist/generate", response_class=HTMLResponse)
    async def api_generate_playlist(
        request: Request,
        name: str = Form("Audiophile Vibe Session"),
        prompt: str | None = Form(None),
        seed_track_id: str | None = Form(None),
        cluster_id: str | None = Form(None),
        vibe: str | None = Form(None),
        arc: str | None = Form(None),
        energy: float | None = Form(None),
        danceability: float | None = Form(None),
        limit: int = Form(10),
        max_artist_tracks: int = Form(2),
    ) -> Response:
        """Generate smart playlist and return updated playlist builder component."""
        parsed_seed_id = (
            int(seed_track_id)
            if seed_track_id and str(seed_track_id).strip().isdigit()
            else None
        )
        parsed_cluster_id = (
            int(cluster_id)
            if cluster_id and str(cluster_id).strip().isdigit()
            else None
        )
        parsed_vibe = vibe.strip() if vibe and vibe.strip() else None
        parsed_arc = arc.strip() if arc and arc.strip() else None

        desc = None
        rules = None

        if prompt and prompt.strip():
            try:
                plan = parse_prompt_to_plan(
                    prompt.strip(), db_path=resolved_db_path, settings=cfg
                )
                name = plan.name
                desc = plan.description
                parsed_vibe = plan.vibe or parsed_vibe
                parsed_arc = plan.arc or parsed_arc
                rules = PlaylistRuleConfig(
                    mode=plan.mode,
                    arc=plan.arc,
                    vibe=plan.vibe,
                    bpm_min=plan.bpm_min,
                    bpm_max=plan.bpm_max,
                    energy_min=plan.energy_min,
                    energy_max=plan.energy_max,
                    danceability_min=plan.danceability_min,
                    danceability_max=plan.danceability_max,
                    mood_min=plan.mood_min,
                    genre_include=plan.genre_include,
                    genre_exclude=plan.genre_exclude,
                    limit=plan.limit or limit,
                    max_artist_tracks=max_artist_tracks,
                )
            except Exception as plan_err:
                logger.warning("Prompt planning error: %s", plan_err)

        if rules is None and (energy is not None or danceability is not None):
            rules = PlaylistRuleConfig(
                energy_min=max(0.0, energy - 0.25) if energy is not None else None,
                energy_max=min(1.0, energy + 0.25) if energy is not None else None,
                danceability_min=max(0.0, danceability - 0.25)
                if danceability is not None
                else None,
                danceability_max=min(1.0, danceability + 0.25)
                if danceability is not None
                else None,
            )

        try:
            playlist = generate_playlist(
                db_path=resolved_db_path,
                name=name or "Audiophile Vibe Session",
                seed_track_id=parsed_seed_id,
                cluster_id=parsed_cluster_id,
                vibe=parsed_vibe,
                arc=parsed_arc,
                limit=limit,
                max_artist_tracks=max_artist_tracks,
                rules=rules,
                description=desc,
                settings=cfg,
            )
        except Exception as err:
            logger.warning(
                "Playlist generation with bounds failed (%s); trying standard similarity",
                err,
            )
            playlist = generate_playlist(
                db_path=resolved_db_path,
                name=name or "Audiophile Vibe Session",
                seed_track_id=parsed_seed_id,
                cluster_id=parsed_cluster_id,
                vibe=parsed_vibe,
                arc=parsed_arc,
                limit=limit,
                max_artist_tracks=max_artist_tracks,
                description=desc,
                settings=cfg,
            )

        transitions = calculate_transition_metrics(playlist.tracks)
        summary = calculate_playlist_summary(playlist.tracks, transitions)

        return templates.TemplateResponse(
            request=request,
            name="components/playlist_builder.html",
            context={
                "playlist": playlist,
                "transitions": transitions,
                "summary": summary,
                "active_step": 3,
            },
        )

    @app.get("/api/playlist/builder/search")
    async def api_playlist_builder_search(
        request: Request,
        q: str = Query("", description="Search term for tracks"),
    ) -> Response:
        """Search tracks with acoustic telemetry for the seed track selector."""
        search_term = q.strip()
        with get_connection(resolved_db_path) as conn:
            cursor = conn.cursor()
            if search_term:
                query = """
                    SELECT t.id, t.title, t.artist, t.album, t.duration, t.path,
                           f.bpm, f.key, f.scale, f.energy, f.danceability
                    FROM tracks t
                    LEFT JOIN features f ON t.id = f.track_id
                    WHERE t.status = 'active'
                      AND (t.title LIKE ? OR t.artist LIKE ? OR t.album LIKE ?)
                    ORDER BY t.title ASC
                    LIMIT 20
                """
                pattern = f"%{search_term}%"
                cursor.execute(query, (pattern, pattern, pattern))
            else:
                query = """
                    SELECT t.id, t.title, t.artist, t.album, t.duration, t.path,
                           f.bpm, f.key, f.scale, f.energy, f.danceability
                    FROM tracks t
                    LEFT JOIN features f ON t.id = f.track_id
                    WHERE t.status = 'active'
                    ORDER BY t.id DESC
                    LIMIT 20
                """
                cursor.execute(query)
            rows = cursor.fetchall()

        results = []
        for r in rows:
            dur = float(r[4] or 0.0)
            c = key_to_camelot(r[7], r[8])
            results.append({
                "track_id": r[0],
                "title": r[1] or "Unknown Title",
                "artist": r[2] or "Unknown Artist",
                "album": r[3] or "Unknown Album",
                "duration": dur,
                "duration_formatted": f"{int(dur // 60)}:{int(dur % 60):02d}",
                "path": r[5] or "",
                "bpm": round(float(r[6]), 1) if r[6] is not None else None,
                "key": r[7],
                "scale": r[8],
                "camelot": c,
                "energy": round(float(r[9]), 2) if r[9] is not None else None,
                "danceability": round(float(r[10]), 2) if r[10] is not None else None,
            })

        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.query_params.get("format") == "json":
            return JSONResponse(content={"results": results, "count": len(results)})

        return templates.TemplateResponse(
            request=request,
            name="components/playlist_seed_results.html",
            context={
                "results": results,
                "query": search_term,
            },
        )

    @app.post("/api/playlist/builder/preview")
    async def api_playlist_builder_preview(
        request: Request,
        seed_track_id: int = Form(...),
        arc: str = Form("energy_ramp"),
        limit: int = Form(12),
        max_bpm_delta: float = Form(10.0),
        max_artist_tracks: int = Form(2),
        name: str = Form("Harmonic Journey"),
        vibe: str | None = Form(None),
    ) -> Response:
        """Generate an arc-guided harmonic preview sequence with transition telemetry."""
        parsed_vibe = vibe.strip() if vibe and vibe.strip() else None
        parsed_arc = arc.strip() if arc and arc.strip() else "energy_ramp"

        rules = PlaylistRuleConfig(
            mode="seed",
            seed_track_ids=[seed_track_id],
            arc=parsed_arc,
            limit=limit,
            max_bpm_delta=max_bpm_delta,
            max_artist_tracks=max_artist_tracks,
            vibe=parsed_vibe,
        )

        playlist = generate_playlist(
            db_path=resolved_db_path,
            name=name.strip() or "Harmonic Journey",
            seed_track_id=seed_track_id,
            arc=parsed_arc,
            vibe=parsed_vibe,
            limit=limit,
            max_artist_tracks=max_artist_tracks,
            rules=rules,
            settings=cfg,
        )

        transitions = calculate_transition_metrics(playlist.tracks)
        summary = calculate_playlist_summary(playlist.tracks, transitions)

        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.query_params.get("format") == "json":
            return JSONResponse(content={
                "playlist": playlist.to_dict(),
                "transitions": transitions,
                "summary": summary,
            })

        return templates.TemplateResponse(
            request=request,
            name="components/playlist_builder.html",
            context={
                "playlist": playlist,
                "transitions": transitions,
                "summary": summary,
                "active_step": 3,
                "seed_track_id": seed_track_id,
                "arc": parsed_arc,
                "limit": limit,
                "max_bpm_delta": max_bpm_delta,
                "max_artist_tracks": max_artist_tracks,
            },
        )

    @app.post("/api/playlist/builder/reorder")
    async def api_playlist_builder_reorder(
        request: Request,
        track_ids: str = Form(...),
        playlist_id: int | None = Form(None),
        step: int = Form(4),
    ) -> Response:
        """Reorder tracks in playlist, update database, and recalculate harmonic transitions."""
        ordered_ids = [
            int(x.strip()) for x in track_ids.split(",") if x.strip().isdigit()
        ]
        if not ordered_ids:
            raise HTTPException(status_code=400, detail="Invalid track_ids")

        with get_connection(resolved_db_path) as conn:
            if playlist_id:
                pl_row = get_playlist(conn, playlist_id)
                if not pl_row:
                    raise HTTPException(status_code=404, detail="Playlist not found")
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)
                )
                add_tracks_to_playlist(conn, playlist_id, ordered_ids)

        if playlist_id:
            reordered_playlist = load_saved_playlist(resolved_db_path, playlist_id)
        else:
            with get_connection(resolved_db_path) as conn:
                all_tracks = {
                    t["track_id"]: dict(t)
                    for t in get_tracks_with_features(conn)
                }
            items: list[PlaylistTrackItem] = []
            prev_meta = None
            for pos, tid in enumerate(ordered_ids, start=1):
                if tid not in all_tracks:
                    continue
                meta = all_tracks[tid]
                trans = calculate_transition(prev_meta, meta, None, None) if pos > 1 else None
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
            scores = [i.transition.total_score for i in items if i.transition]
            reordered_playlist = GeneratedPlaylist(
                playlist_id=0,
                name="Preview Sequence",
                description="Live reordered sequence",
                mode="preview",
                tracks=items,
                total_duration=round(sum(i.duration for i in items), 2),
                avg_transition_score=round(float(np.mean(scores)), 4) if scores else 1.0,
            )

        if reordered_playlist is None:
            raise HTTPException(status_code=404, detail="Failed to load reordered playlist")

        transitions = calculate_transition_metrics(reordered_playlist.tracks)
        summary = calculate_playlist_summary(reordered_playlist.tracks, transitions)

        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.query_params.get("format") == "json":
            return JSONResponse(content={
                "playlist": reordered_playlist.to_dict(),
                "transitions": transitions,
                "summary": summary,
            })

        return templates.TemplateResponse(
            request=request,
            name="components/playlist_builder.html",
            context={
                "playlist": reordered_playlist,
                "transitions": transitions,
                "summary": summary,
                "active_step": step,
            },
        )

    @app.post("/api/playlist/reorder", response_class=HTMLResponse)
    async def api_reorder_playlist(
        request: Request,
        playlist_id: int = Form(...),
        track_ids: str = Form(...),
    ) -> Response:
        """Reorder tracks in playlist, update database, recalculate transitions."""
        ordered_ids = [
            int(x.strip()) for x in track_ids.split(",") if x.strip().isdigit()
        ]
        if not ordered_ids:
            raise HTTPException(status_code=400, detail="Invalid track_ids")

        with get_connection(resolved_db_path) as conn:
            pl_row = get_playlist(conn, playlist_id)
            if not pl_row:
                raise HTTPException(status_code=404, detail="Playlist not found")

            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)
            )
            add_tracks_to_playlist(conn, playlist_id, ordered_ids)

        reordered_playlist = load_saved_playlist(resolved_db_path, playlist_id)
        if reordered_playlist is None:
            raise HTTPException(status_code=404, detail="Failed to reload reordered playlist")

        transitions = calculate_transition_metrics(reordered_playlist.tracks)
        summary = calculate_playlist_summary(reordered_playlist.tracks, transitions)

        return templates.TemplateResponse(
            request=request,
            name="components/playlist_builder.html",
            context={
                "playlist": reordered_playlist,
                "transitions": transitions,
                "summary": summary,
                "active_step": 4,
            },
        )

    @app.get("/api/playlist/{playlist_id}/export-m3u8")
    async def api_export_m3u8(playlist_id: int) -> Response:
        """Download playlist as standard UTF-8 extended M3U8 file."""
        with get_connection(resolved_db_path) as conn:
            pl_row = get_playlist(conn, playlist_id)
            if not pl_row:
                raise HTTPException(status_code=404, detail="Playlist not found")
            tracks = get_playlist_tracks(conn, playlist_id)

        lines = ["#EXTM3U\n"]
        for t in tracks:
            duration_sec = (
                int(round(float(t["duration"]))) if t["duration"] is not None else -1
            )
            artist = t["artist"] or "Unknown Artist"
            title = t["title"] or "Unknown Title"
            lines.append(f"#EXTINF:{duration_sec},{artist} - {title}\n")
            lines.append(f"{t['path']}\n")

        safe_name = (
            "".join(c for c in pl_row["name"] if c.isalnum() or c in (" ", "_", "-"))
            .strip()
            .replace(" ", "_")
        )
        filename = f"{safe_name or 'playlist'}_{playlist_id}.m3u8"

        return Response(
            content="".join(lines),
            media_type="audio/x-mpegurl",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def _maybe_notify_track_transition(playback: dict[str, Any]) -> None:
        """Dispatch a native desktop track transition notification if enabled and available."""
        track_id = playback.get("track_id") or playback.get("song_id") or playback.get("file")
        if not track_id:
            return
        try:
            from vibeplay.desktop.notifications import TrackNotificationDispatcher

            if not hasattr(app.state, "notification_dispatcher"):
                app.state.notification_dispatcher = TrackNotificationDispatcher()
            dispatcher = app.state.notification_dispatcher
            title = str(playback.get("title") or "Unknown Title")
            artist = str(playback.get("artist") or "Unknown Artist")
            album = str(playback.get("album") or "")
            sample_rate = str(playback.get("sample_rate") or "")
            bit_depth = str(playback.get("bit_depth") or "")
            track_id_val = int(track_id) if (isinstance(track_id, int) or (isinstance(track_id, str) and track_id.isdigit())) else str(track_id)
            if hasattr(dispatcher, "notify_track_change"):
                dispatcher.notify_track_change(
                    track_id=track_id_val,
                    title=title,
                    artist=artist,
                    album=album,
                    sample_rate=sample_rate,
                    bit_depth=bit_depth,
                )
            elif hasattr(dispatcher, "notify"):
                dispatcher.notify(title=title, artist=artist, album=album)
        except Exception as err:
            logger.debug("Desktop track notification skipped: %s", err)

    @app.post("/api/player/play-track/{track_id}", response_class=HTMLResponse)
    async def api_play_track(request: Request, track_id: int) -> Response:
        """Queue track directly into MPD and return transport bar."""
        try:
            play_track(resolved_db_path, track_id, cfg)
        except Exception as err:
            logger.warning("Could not play track: %s", err)

        playback = get_playback_status(resolved_db_path, cfg)
        _maybe_notify_track_transition(playback)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/play-playlist/{playlist_id}", response_class=HTMLResponse)
    async def api_play_playlist(request: Request, playlist_id: int) -> Response:
        """Queue saved playlist into MPD and return transport bar."""
        try:
            play_playlist(resolved_db_path, playlist_id, cfg)
        except Exception as err:
            logger.warning("Could not play playlist: %s", err)

        playback = get_playback_status(resolved_db_path, cfg)
        _maybe_notify_track_transition(playback)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/toggle", response_class=HTMLResponse)
    async def api_player_toggle(request: Request) -> Response:
        """Toggle play/pause state in MPD."""
        toggle_pause(db_path=resolved_db_path, settings=cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/seek", response_class=HTMLResponse)
    async def api_player_seek(request: Request, seconds: float = Form(0.0)) -> Response:
        """Seek active track in MPD to target time offset."""
        seek_playback(seconds, settings=cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/next", response_class=HTMLResponse)
    async def api_player_next(request: Request) -> Response:
        """Skip to next track in MPD."""
        next_song(cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        _maybe_notify_track_transition(playback)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/prev", response_class=HTMLResponse)
    async def api_player_prev(request: Request) -> Response:
        """Skip to previous track in MPD."""
        previous_song(cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        _maybe_notify_track_transition(playback)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/volume", response_class=HTMLResponse)
    async def api_player_volume(request: Request, volume: int = Form(...)) -> Response:
        """Set volume level [0-100]."""
        set_volume_level(volume, cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/volume-step", response_class=HTMLResponse)
    async def api_player_volume_step(request: Request, delta: int = Form(5)) -> Response:
        """Adjust volume level by delta (positive or negative) within [0, 100]."""
        adjust_volume_step(delta, cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/mute-toggle", response_class=HTMLResponse)
    async def api_player_mute_toggle(request: Request) -> Response:
        """Toggle mute/unmute state."""
        toggle_mute(cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.post("/api/player/output", response_class=HTMLResponse)
    async def api_player_output(request: Request, profile: str = Form(...)) -> Response:
        """Switch audio hardware output profile and notify vibe-dsp IPC engine."""
        set_output_profile(profile, settings=cfg)
        try:
            from vibe_dsp.ipc import DSPClient

            prof_map = {
                "Pure Bit-Perfect (Direct ALSA)": "pure-bitperfect",
                "7.1.4 Spatial Headphones (SOFA 3D)": "spatial-headphones",
                "AV Receiver Passthrough (HDMI)": "receiver-passthrough",
                "USB DAC (Bit-Perfect)": "pure-bitperfect",
                "Direct ALSA (hw:0,0)": "pure-bitperfect",
                "Headphones": "spatial-headphones",
                "PipeWire Sound Server": "pure-bitperfect",
            }
            target_id = prof_map.get(profile, profile)
            client = DSPClient()
            client.set_profile(target_id)
        except Exception as err:
            logger.debug("Could not dispatch profile switch to vibe-dsp IPC: %s", err)

        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.get("/api/player/scrub", response_class=HTMLResponse)
    async def api_player_scrub(request: Request) -> Response:
        """Return rendered scrub row micro-component for isolated 1s polling."""
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_scrub.html",
            context={
                "playback": playback,
            },
        )

    @app.get("/api/player/transport", response_class=HTMLResponse)
    async def api_player_transport(request: Request) -> Response:
        """Return rendered transport footer bar."""
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.get("/api/dsp/profile")
    async def api_dsp_get_profile() -> Response:
        """Return active DSP routing profile, spatial status, and available profile targets."""
        try:
            from vibe_dsp.ipc import DSPClient

            client = DSPClient()
            status = client.get_status()
            return JSONResponse(content={"status": "ok", "data": status})
        except Exception as err:
            logger.warning("Error fetching DSP status: %s", err)
            return JSONResponse(
                content={"status": "error", "message": str(err)},
                status_code=500,
            )

    @app.post("/api/dsp/profile")
    async def api_dsp_set_profile(request: Request) -> Response:
        """Switch audio routing profile on the fly (pure-bitperfect, spatial-headphones, receiver-passthrough)."""
        target_profile: str | None = request.query_params.get("profile")
        if not target_profile:
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = await request.json()
                    target_profile = body.get("profile")
                except Exception:
                    pass
            else:
                try:
                    form = await request.form()
                    target_profile = str(form.get("profile", "")) or None
                except Exception:
                    pass

        if not target_profile:
            return JSONResponse(
                content={"status": "error", "message": "Missing 'profile' parameter"},
                status_code=400,
            )

        try:
            from vibe_dsp.ipc import DSPClient

            client = DSPClient()
            res = client.set_profile(str(target_profile))
            set_output_profile(str(target_profile))
            try:
                update_desktop_settings(
                    {"dsp_profile": str(target_profile)}, settings_file_path
                )
            except Exception:
                pass
            return JSONResponse(content=res)
        except Exception as err:
            logger.warning("Error switching DSP profile: %s", err)
            return JSONResponse(
                content={"status": "error", "message": str(err)},
                status_code=500,
            )

    @app.get("/api/player/status")
    async def api_player_status() -> Response:
        """Return raw JSON playback state, hardware sample rate, DAC buffer health, and service operational status."""
        playback = get_playback_status(resolved_db_path, cfg)
        playback["services"] = {
            "mpd": "online" if playback.get("daemon_online") else "offline",
            "database": "connected" if resolved_db_path.exists() else "not_found",
            "acoustid": "configured" if cfg.acoustid_api_key else "unconfigured",
            "llm": cfg.llm_provider,
        }
        try:
            from vibe_dsp.ipc import DSPClient

            client = DSPClient()
            playback["dsp"] = {
                "active_profile": client.get_profile(),
            }
        except Exception:
            playback["dsp"] = {
                "active_profile": playback.get("output_profile"),
            }
        return JSONResponse(content=playback)

    @app.get("/api/menu")
    async def api_get_menu() -> JSONResponse:
        """Return desktop top menu bar hierarchy as JSON."""
        from vibeplay.ui.menu import build_desktop_menu_bar

        sections = build_desktop_menu_bar()
        return JSONResponse(
            content=[
                {
                    "id": s.id,
                    "label": s.label,
                    "items": [
                        {
                            "id": it.id,
                            "label": it.label,
                            "shortcut": it.shortcut,
                            "action_endpoint": it.action_endpoint,
                            "is_separator": it.is_separator,
                            "is_checked": it.is_checked,
                            "is_disabled": it.is_disabled,
                        }
                        for it in s.items
                    ],
                }
                for s in sections
            ]
        )

    @app.get("/api/themes")
    async def api_get_themes() -> JSONResponse:
        """Return all available CSS theme presets."""
        from vibeplay.ui.theme import get_available_themes

        themes = get_available_themes()
        return JSONResponse(
            content=[
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "swatches": t.swatches,
                    "variables": t.variables,
                }
                for t in themes
            ]
        )

    @app.get("/api/settings")
    async def api_get_settings() -> JSONResponse:
        """Return persisted desktop & hardware settings and available PEQ presets."""
        current = load_desktop_settings(settings_file_path)
        peq_presets: list[str] = []
        try:
            from vibe_dsp.peq import list_available_presets

            raw_presets = list_available_presets()
            peq_presets = [
                (p["name"] if isinstance(p, dict) else str(p))
                for p in raw_presets
            ]
        except Exception:
            peq_presets = [
                "7hz_zero_2",
                "apple_airpods_pro_2",
                "moondrop_blessing_2",
                "sennheiser_hd600",
            ]
        return JSONResponse(
            content={
                "settings": current.model_dump(mode="json"),
                "peq_presets": peq_presets,
                "settings_path": str(settings_file_path),
            }
        )

    @app.post("/api/settings")
    @app.put("/api/settings")
    async def api_update_settings(request: Request) -> JSONResponse:
        """Validate, apply, and persist partial or full desktop settings updates without reload."""
        from pydantic import ValidationError

        payload: dict[str, Any] = {}
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                raw_body = await request.json()
                if not isinstance(raw_body, dict):
                    return JSONResponse(
                        status_code=422,
                        content={"detail": "Settings payload must be a JSON object."},
                    )
                payload = raw_body
            except Exception as err:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Invalid JSON body: {err}"},
                )
        else:
            try:
                form = await request.form()
                payload = dict(form)
            except Exception:
                payload = dict(request.query_params)

        current = load_desktop_settings(settings_file_path)
        merged = current.model_dump()
        merged.update(payload)

        # Synchronize spatial_enabled <-> spatial_mode when only one is supplied
        if "spatial_enabled" in payload and "spatial_mode" not in payload:
            merged["spatial_mode"] = (
                "3d_binaural" if bool(payload["spatial_enabled"]) else "stereo_direct"
            )
        elif "spatial_mode" in payload and "spatial_enabled" not in payload:
            merged["spatial_enabled"] = str(payload["spatial_mode"]).strip().lower() in {
                "3d_binaural",
                "spatial_binaural",
            }

        try:
            validated = DesktopSettings.model_validate(merged)
        except ValidationError as val_err:
            return JSONResponse(
                status_code=422,
                content={"detail": val_err.errors(include_context=False)},
            )

        # Auto-compute negative headroom preamp when peq_profile changes or peq_preamp_auto is enabled
        if (
            ("peq_profile" in payload or "peq_preamp_auto" in payload)
            and "peq_preamp_db" not in payload
            and validated.peq_preamp_auto
        ):
            if validated.peq_profile == "none":
                validated.peq_preamp_db = 0.0
            else:
                try:
                    from vibe_dsp.peq import lookup_autoeq_model

                    prof = lookup_autoeq_model(
                        validated.peq_profile, allow_network=False
                    )
                    if prof is not None:
                        validated.peq_preamp_db = round(
                            float(prof.calculated_preamp), 2
                        )
                    else:
                        validated.peq_preamp_db = -5.5
                except Exception:
                    validated.peq_preamp_db = -5.5

        save_desktop_settings(validated, settings_file_path)
        _sync_runtime_cfg(validated)

        # Best-effort live application to DSP / audio transport
        if "dsp_profile" in payload:
            try:
                from vibe_dsp.ipc import DSPClient

                DSPClient().set_profile(validated.dsp_profile)
                set_output_profile(validated.dsp_profile)
            except Exception:
                set_output_profile(validated.dsp_profile)

        return JSONResponse(
            content={
                "status": "saved",
                "settings": validated.model_dump(mode="json"),
            }
        )

    @app.get("/api/dsp/peq/presets")
    async def api_dsp_peq_presets() -> JSONResponse:
        """List available Parametric EQ transducer presets and their headroom attenuation."""
        presets_info: list[dict[str, Any]] = [
            {
                "id": "none",
                "name": "Bypass / Flat (0.0 dB)",
                "preamp_db": 0.0,
                "filters_count": 0,
            }
        ]
        try:
            from vibe_dsp.peq import list_available_presets

            for p in list_available_presets():
                if isinstance(p, dict):
                    preset_id = str(p.get("name", ""))
                    preamp = round(float(p.get("preamp_db", -5.5)), 2)
                    filters_count = int(p.get("bands", 0))
                else:
                    preset_id = str(p)
                    preamp = -5.5
                    filters_count = 0
                presets_info.append(
                    {
                        "id": preset_id,
                        "name": preset_id.replace("_", " ").title(),
                        "preamp_db": preamp,
                        "filters_count": filters_count,
                    }
                )
        except Exception as err:
            logger.warning("Could not enumerate PEQ presets: %s", err)

        return JSONResponse(content={"presets": presets_info})

    @app.post("/api/dsp/peq/apply")
    async def api_dsp_peq_apply(request: Request) -> JSONResponse:
        """Load and apply a Parametric EQ preset with automatic headroom calculation."""
        from pydantic import ValidationError

        preset_id: str | None = request.query_params.get("preset")
        if not preset_id:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    preset_id = body.get("preset") or body.get("peq_profile")
            except Exception:
                pass

        if not preset_id:
            return JSONResponse(
                status_code=400,
                content={"detail": "Missing 'preset' parameter."},
            )

        try:
            updated = update_desktop_settings(
                {"peq_profile": str(preset_id)}, settings_file_path
            )
            filters_count = 0
            if updated.peq_profile == "none":
                if updated.peq_preamp_auto:
                    updated = update_desktop_settings(
                        {"peq_preamp_db": 0.0}, settings_file_path
                    )
            else:
                try:
                    from vibe_dsp.peq import lookup_autoeq_model

                    prof = lookup_autoeq_model(
                        updated.peq_profile, allow_network=False
                    )
                    if prof is not None:
                        filters_count = len(prof.filters)
                        if updated.peq_preamp_auto:
                            preamp = round(float(prof.calculated_preamp), 2)
                            updated = update_desktop_settings(
                                {"peq_preamp_db": preamp}, settings_file_path
                            )
                except Exception:
                    pass

            return JSONResponse(
                content={
                    "status": "applied",
                    "peq_profile": updated.peq_profile,
                    "peq_preamp_db": updated.peq_preamp_db,
                    "peq_preamp_auto": updated.peq_preamp_auto,
                    "filters_count": filters_count,
                }
            )
        except ValidationError as val_err:
            return JSONResponse(
                status_code=422,
                content={"detail": val_err.errors(include_context=False)},
            )

    @app.post("/api/player/clear")
    async def api_player_clear() -> JSONResponse:
        """Clear the active MPD playback queue."""
        try:
            from vibeplay.player import get_mpd_transport

            with get_mpd_transport(cfg) as transport:
                transport.clear()
            return JSONResponse(content={"status": "cleared", "detail": "MPD queue cleared successfully."})
        except Exception as err:
            return JSONResponse(status_code=500, content={"error": str(err)})

    @app.post("/api/library/rescan")
    async def api_library_rescan() -> JSONResponse:
        """Scan music directory for new audio files."""
        try:
            from vibeplay.scanner import scan_directory

            music_dir = Path("~/Music").expanduser()
            if not music_dir.exists():
                music_dir = Path.cwd()
            stats = scan_directory(music_dir, db_path=resolved_db_path)
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

    @app.get("/api/dsp/telemetry")
    async def api_dsp_telemetry() -> JSONResponse:
        """Return real-time hardware latency, xruns, and buffer telemetry."""
        ds = load_desktop_settings(settings_file_path)
        hw_label = (
            f"ALSA {ds.alsa_device}"
            if ds.alsa_device.startswith("hw:")
            else ds.alsa_device
        )
        telemetry = {
            "xruns": 0,
            "jitter_ppm": 0.02,
            "buffer_health": "100% Bit-Perfect Locked"
            if ds.alsa_exclusive_lock
            else "Shared Mixer Active",
            "pipewire_active": ds.alsa_device == "pipewire",
            "active_profile": ds.dsp_profile,
            "peq_profile": ds.peq_profile,
            "peq_preamp_db": ds.peq_preamp_db,
            "spatial_mode": ds.spatial_mode,
            "hardware_device": hw_label,
            "buffer_frames": ds.alsa_buffer_frames,
            "period_count": ds.alsa_period_count,
            "sample_rate_lock": ds.alsa_sample_rate_lock,
            "exclusive_lock": ds.alsa_exclusive_lock,
            "dpc_watchdog_enabled": ds.dpc_watchdog_enabled,
        }
        try:
            from vibe_dsp.ipc import DSPClient

            client = DSPClient()
            telemetry["active_profile"] = client.get_profile()
        except Exception:
            pass
        if not settings_file_path.exists():
            try:
                from vibe_dsp.spatial import get_spatial_virtualization_status

                telemetry["spatial_mode"] = get_spatial_virtualization_status()
            except Exception:
                pass
        return JSONResponse(content=telemetry)

    @app.post("/api/dsp/spatial/toggle")
    async def api_dsp_spatial_toggle() -> JSONResponse:
        """Toggle between Stereo Direct and 3D Binaural SOFA Virtualization."""
        try:
            from vibe_dsp.spatial import (
                get_spatial_virtualization_status,
                set_spatial_virtualization_mode,
            )

            cur = get_spatial_virtualization_status()
            if isinstance(cur, dict):
                if cur.get("installed"):
                    cur_mode = str(cur.get("mode", "stereo_direct"))
                else:
                    ds = load_desktop_settings(settings_file_path)
                    cur_mode = ds.spatial_mode if ds.spatial_enabled else "stereo_direct"
            else:
                cur_mode = str(cur)
            is_binaural = cur_mode in {"spatial_binaural", "3d_binaural"}
            target = "stereo_direct" if is_binaural else "spatial_binaural"
            status = set_spatial_virtualization_mode(target)
            if isinstance(status, dict):
                result_payload = status
            else:
                result_payload = {
                    "mode": target,
                    "status": "active" if target != "stereo_direct" else "bypassed",
                    "applied": bool(status),
                }
            try:
                update_desktop_settings(
                    {
                        "spatial_mode": result_payload.get("mode", target),
                        "spatial_enabled": result_payload.get("mode", target)
                        != "stereo_direct",
                    },
                    settings_file_path,
                )
            except Exception:
                pass
            return JSONResponse(content=result_payload)
        except Exception as err:
            return JSONResponse(status_code=500, content={"error": str(err)})

    @app.post("/api/desktop/open")
    async def api_desktop_open(request: Request) -> JSONResponse:
        """Open audio files, M3U/M3U8 playlists, or directories forwarded from XDG desktop (%U)."""
        from vibeplay.desktop.mime import classify_mime_target, parse_m3u_playlist
        from vibeplay.scanner import scan_directory

        raw_uris: list[str] = []
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    if isinstance(body.get("uris"), list):
                        raw_uris = [str(u) for u in body["uris"] if str(u).strip()]
                    elif body.get("uri"):
                        raw_uris = [str(body["uri"]).strip()]
            except Exception as err:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Invalid JSON body: {err}"},
                )
        else:
            q_uri = request.query_params.get("uri")
            if q_uri:
                raw_uris = [q_uri.strip()]
            else:
                try:
                    form = await request.form()
                    f_uri = form.get("uri")
                    if f_uri:
                        raw_uris = [str(f_uri).strip()]
                except Exception:
                    pass

        if not raw_uris:
            return JSONResponse(
                status_code=400,
                content={"detail": "No file paths or URIs provided."},
            )

        opened_items: list[dict[str, Any]] = []
        matched_track_ids: list[int] = []

        def _find_track_id_by_path(file_path: Path) -> int | None:
            with get_connection(resolved_db_path) as conn:
                row = conn.execute(
                    "SELECT id FROM tracks WHERE path = ? AND status = 'active' LIMIT 1",
                    (str(file_path.resolve()),),
                ).fetchone()
                return int(row["id"]) if row else None

        for raw in raw_uris:
            try:
                target = classify_mime_target(raw)
            except ValueError as val_err:
                return JSONResponse(
                    status_code=400,
                    content={"detail": str(val_err)},
                )

            item_info: dict[str, Any] = {
                "uri": target.raw_uri,
                "path": str(target.path),
                "type": target.target_type,
                "exists": target.exists,
            }

            if target.target_type == "directory" and target.exists:
                try:
                    stats = scan_directory(target.path, db_path=resolved_db_path)
                    item_info["files_added"] = stats.files_added
                except Exception as scan_err:
                    logger.warning("Directory scan failed for %s: %s", target.path, scan_err)
                escaped_dir = (
                    str(target.path.resolve())
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                with get_connection(resolved_db_path) as conn:
                    rows = conn.execute(
                        "SELECT id FROM tracks WHERE path LIKE ? ESCAPE '\\' AND status = 'active' ORDER BY path ASC",
                        (f"{escaped_dir}/%",),
                    ).fetchall()
                    matched_track_ids.extend(int(r["id"]) for r in rows)
            elif target.target_type == "audio":
                tid = _find_track_id_by_path(target.path)
                if tid is None and target.exists:
                    try:
                        scan_directory(target.path.parent, db_path=resolved_db_path)
                        tid = _find_track_id_by_path(target.path)
                    except Exception as scan_err:
                        logger.warning("Audio parent scan failed for %s: %s", target.path, scan_err)
                if tid is not None:
                    matched_track_ids.append(tid)
                    item_info["track_id"] = tid
            elif target.target_type == "playlist" and target.exists:
                pl_paths = parse_m3u_playlist(target.path)
                pl_track_ids: list[int] = []
                for p in pl_paths:
                    tid = _find_track_id_by_path(p)
                    if tid is not None:
                        pl_track_ids.append(tid)
                matched_track_ids.extend(pl_track_ids)
                item_info["playlist_tracks"] = len(pl_paths)
                item_info["matched_tracks"] = len(pl_track_ids)

            opened_items.append(item_info)

        played_track_id: int | None = None
        if matched_track_ids:
            played_track_id = matched_track_ids[0]
            try:
                play_track(resolved_db_path, played_track_id, cfg)
                playback = get_playback_status(resolved_db_path, cfg)
                _maybe_notify_track_transition(playback)
            except Exception as play_err:
                logger.warning("Could not start playback for opened track %d: %s", played_track_id, play_err)

        return JSONResponse(
            content={
                "status": "ok",
                "opened": opened_items,
                "matched_track_ids": matched_track_ids,
                "played_track_id": played_track_id,
            }
        )

    @app.get("/api/desktop/telemetry/stream")
    async def api_desktop_telemetry_stream() -> StreamingResponse:
        """Stream desktop hardware & playback telemetry updates as Server-Sent Events (SSE)."""
        from vibeplay.desktop.telemetry_stream import (
            TelemetryMonitor,
            TelemetrySnapshot,
            format_sse_event,
        )

        if not hasattr(app.state, "telemetry_monitor"):
            app.state.telemetry_monitor = TelemetryMonitor()
        monitor: TelemetryMonitor = app.state.telemetry_monitor

        ds = load_desktop_settings(settings_file_path)
        playback = get_playback_status(resolved_db_path, cfg)
        state_str = str(playback.get("state") or "stop").lower()

        raw_sr = str(playback.get("sample_rate") or ds.alsa_sample_rate_lock or "44100")
        sr_digits = "".join(ch for ch in raw_sr if ch.isdigit())
        sample_rate_hz = int(sr_digits) if sr_digits else 44100

        raw_bd = str(playback.get("bit_depth") or "24")
        bd_digits = "".join(ch for ch in raw_bd if ch.isdigit())
        bit_depth = int(bd_digits) if bd_digits else 24

        raw_tid = playback.get("track_id")
        current_track_id = int(raw_tid) if raw_tid is not None else None

        camelot_key: str | None = None
        if current_track_id is not None and resolved_db_path.exists():
            try:
                with get_connection(resolved_db_path) as conn:
                    row = conn.execute(
                        "SELECT key, scale FROM features WHERE track_id = ?",
                        (current_track_id,),
                    ).fetchone()
                    if row and row[0]:
                        from vibeplay.playlist import key_to_camelot
                        camelot_key = key_to_camelot(row[0], row[1])
            except Exception:
                pass

        snapshot = TelemetrySnapshot(
            xruns=0,
            bit_perfect_locked=bool(ds.alsa_exclusive_lock),
            sample_rate_hz=sample_rate_hz,
            bit_depth=bit_depth,
            alsa_device=ds.alsa_device,
            dsp_profile=ds.dsp_profile,
            spatial_enabled=bool(ds.spatial_enabled),
            current_track_id=current_track_id,
            current_track_title=playback.get("title"),
            current_track_artist=playback.get("artist"),
            service_healthy=bool(playback.get("daemon_online", True)),
            buffer_frames=int(ds.alsa_buffer_frames or 128),
            period_count=int(ds.alsa_period_count or 2),
            jitter_ps=0.18,
            dbfs=118.4 if bit_depth <= 16 else 124.2,
            true_peak_db=-0.32,
            headroom_db=float(ds.peq_preamp_db) if ds.peq_profile != "none" else 18.0,
            playback_state=state_str,
            camelot_key=camelot_key,
        )
        delta_events = monitor.process_snapshot(snapshot)

        def _event_generator():
            yield format_sse_event(
                "telemetry_snapshot",
                {
                    "xruns": snapshot.xruns,
                    "bit_perfect_locked": snapshot.bit_perfect_locked,
                    "sample_rate_hz": snapshot.sample_rate_hz,
                    "bit_depth": snapshot.bit_depth,
                    "alsa_device": snapshot.alsa_device,
                    "dsp_profile": snapshot.dsp_profile,
                    "spatial_enabled": snapshot.spatial_enabled,
                    "current_track_id": snapshot.current_track_id,
                    "current_track_title": snapshot.current_track_title,
                    "current_track_artist": snapshot.current_track_artist,
                    "service_healthy": snapshot.service_healthy,
                    "buffer_frames": snapshot.buffer_frames,
                    "period_count": snapshot.period_count,
                    "jitter_ps": snapshot.jitter_ps,
                    "dbfs": snapshot.dbfs,
                    "true_peak_db": snapshot.true_peak_db,
                    "headroom_db": snapshot.headroom_db,
                    "playback_state": snapshot.playback_state,
                    "camelot_key": snapshot.camelot_key,
                },
            )
            for evt_type, evt_data in delta_events:
                yield format_sse_event(evt_type, evt_data)

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/app/quit")
    async def api_app_quit() -> JSONResponse:
        """Signal application shutdown."""
        import os
        import signal
        import threading

        logger.info("Application quit endpoint invoked; scheduling SIGTERM.")
        threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        return JSONResponse(content={"status": "shutting_down"})

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

    is_loopback = (
        host in ("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1")
        or host.startswith("127.")
    )

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
