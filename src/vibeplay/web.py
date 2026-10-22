"""Local web UI and API server module using FastAPI, Jinja2, and HTMX."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from vibeplay.config import Settings, get_settings
from vibeplay.db import (
    add_tracks_to_playlist,
    get_connection,
    get_playlist,
    get_playlist_tracks,
)
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
    calculate_transition,
    generate_playlist,
    key_to_camelot,
)
from vibeplay.llm import parse_prompt_to_plan
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
        "bpm_asc": "ORDER BY f.bpm ASC",
        "bpm_desc": "ORDER BY f.bpm DESC",
        "energy_desc": "ORDER BY f.energy DESC",
        "title_asc": "ORDER BY LOWER(v.title) ASC",
        "artist_asc": "ORDER BY LOWER(v.artist) ASC",
        "id_asc": "ORDER BY t.id ASC",
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

        # Filter by mood if requested (>= 50%)
        if mood_filter:
            mood_scores = {}
            if row_dict.get("mood_scores"):
                try:
                    mood_scores = json.loads(row_dict["mood_scores"])
                except Exception:
                    pass
            if mood_scores.get(mood_filter, 0.0) < 0.50:
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
    db_path: Path | None = None, settings: Settings | None = None
) -> FastAPI:
    """Create and configure the FastAPI web application.

    Args:
        db_path: Path to SQLite database file.
        settings: Application settings.

    Returns:
        FastAPI: Configured web application instance.
    """
    cfg = settings or get_settings()
    resolved_db_path = db_path or cfg.db_path

    app = FastAPI(
        title="vibeplay",
        description="Audiophile Precision Audio Analysis, Vibe Clustering & Smart Playlist Server",
        version="0.1.0",
    )

    static_dir = Path(__file__).parent / "static"
    templates_dir = Path(__file__).parent / "templates"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/", response_class=HTMLResponse)
    async def index_page(request: Request) -> Response:
        """Render the main console dashboard shell."""
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
                WHERE t.status = 'active' AND artist_name IS NOT NULL
                ORDER BY LOWER(artist_name) ASC
                """
            )
            artists = [r[0] for r in cursor.fetchall() if r[0]]
            tracks = get_filtered_tracks(conn)

            cursor.execute("SELECT id FROM playlists ORDER BY id DESC LIMIT 1")
            recent_pl = cursor.fetchone()

        latest_playlist = None
        if recent_pl:
            try:
                latest_playlist = load_saved_playlist(resolved_db_path, recent_pl[0])
            except Exception as err:
                logger.debug("Could not load recent playlist: %s", err)

        clusters = get_library_clusters(resolved_db_path, cfg)
        playback = get_playback_status(resolved_db_path, cfg)

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
                "playback": playback,
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
            )

        return templates.TemplateResponse(
            request=request,
            name="components/library_table.html",
            context={
                "tracks": tracks,
            },
        )

    @app.get("/api/track/{track_id}", response_class=HTMLResponse)
    async def api_track_detail(request: Request, track_id: int) -> Response:
        """HTMX endpoint returning track detail modal content."""
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

        return templates.TemplateResponse(
            request=request,
            name="components/track_detail.html",
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

        return templates.TemplateResponse(
            request=request,
            name="components/playlist_builder.html",
            context={
                "playlist": playlist,
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

        return templates.TemplateResponse(
            request=request,
            name="components/playlist_builder.html",
            context={
                "playlist": reordered_playlist,
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

    @app.post("/api/player/play-track/{track_id}", response_class=HTMLResponse)
    async def api_play_track(request: Request, track_id: int) -> Response:
        """Queue track directly into MPD and return transport bar."""
        try:
            play_track(resolved_db_path, track_id, cfg)
        except Exception as err:
            logger.warning("Could not play track: %s", err)

        playback = get_playback_status(resolved_db_path, cfg)
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
        """Switch audio hardware output profile."""
        set_output_profile(profile)
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.get("/api/player/transport", response_class=HTMLResponse)
    async def api_player_transport(request: Request) -> Response:
        """Return rendered transport footer bar for 2s polling."""
        playback = get_playback_status(resolved_db_path, cfg)
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @app.get("/api/player/status")
    async def api_player_status() -> Response:
        """Return raw JSON playback state, hardware sample rate, and DAC buffer health."""
        playback = get_playback_status(resolved_db_path, cfg)
        return JSONResponse(content=playback)

    return app


def run_server(
    db_path: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Start the local vibeplay web server.

    Args:
        db_path: Path to the SQLite database.
        host: Host address to bind to (defaults to 127.0.0.1).
        port: Port number to bind to (defaults to 8000).
    """
    logger.info(
        "Starting web server at http://%s:%d with database %s", host, port, db_path
    )
    app = create_app(db_path=db_path)
    uvicorn.run(app, host=host, port=port)
