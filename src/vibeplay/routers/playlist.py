import logging

import numpy as np
from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from vibeplay.db import (
    add_tracks_to_playlist,
    delete_saved_playlist,
    get_connection,
    get_playlist,
    get_playlist_tracks,
    get_tracks_with_features,
    save_playlist,
)
from vibeplay.playlist import (
    GeneratedPlaylist,
    PlaylistRuleConfig,
    PlaylistTrackItem,
    calculate_playlist_summary,
    calculate_transition,
    calculate_transition_metrics,
    generate_playlist,
    key_to_camelot,
    parse_natural_language_prompt,
)
from vibeplay.web import load_saved_playlist

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/clusters/cards", response_class=HTMLResponse)
async def api_cluster_cards(request: Request) -> Response:
    """HTMX endpoint returning cluster cards component (purged in lean core)."""
    return HTMLResponse("<div class='hidden'></div>")


@router.post("/api/playlist/generate", response_class=HTMLResponse)
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
    parsed_seed_id = int(seed_track_id) if seed_track_id and str(seed_track_id).strip().isdigit() else None
    parsed_cluster_id = int(cluster_id) if cluster_id and str(cluster_id).strip().isdigit() else None
    parsed_vibe = vibe.strip() if vibe and vibe.strip() else None
    parsed_arc = arc.strip() if arc and arc.strip() else None

    desc = None
    rules = None

    if prompt and prompt.strip():
        try:
            nl_query = parse_natural_language_prompt(prompt.strip())
            name = prompt.strip().title()
            desc = f"Smart playlist for '{prompt.strip()}'"
            parsed_vibe = nl_query.vibe or parsed_vibe
            parsed_arc = nl_query.arc or parsed_arc
            rules = PlaylistRuleConfig(
                mode="rules",
                arc=nl_query.arc,
                vibe=nl_query.vibe,
                bpm_min=nl_query.bpm_min,
                bpm_max=nl_query.bpm_max,
                energy_min=nl_query.energy_min,
                energy_max=nl_query.energy_max,
                danceability_min=nl_query.danceability_min,
                danceability_max=nl_query.danceability_max,
                genre_include=[nl_query.genre_like] if nl_query.genre_like else None,
                limit=nl_query.limit or limit,
                max_artist_tracks=max_artist_tracks,
            )
        except Exception as plan_err:
            logger.warning("Prompt planning error: %s", plan_err)

    if rules is None and (energy is not None or danceability is not None):
        rules = PlaylistRuleConfig(
            energy_min=max(0.0, energy - 0.25) if energy is not None else None,
            energy_max=min(1.0, energy + 0.25) if energy is not None else None,
            danceability_min=max(0.0, danceability - 0.25) if danceability is not None else None,
            danceability_max=min(1.0, danceability + 0.25) if danceability is not None else None,
        )

    try:
        playlist = generate_playlist(
            db_path=request.app.state.db_path,
            name=name or "Audiophile Vibe Session",
            seed_track_id=parsed_seed_id,
            cluster_id=parsed_cluster_id,
            vibe=parsed_vibe,
            arc=parsed_arc,
            limit=limit,
            max_artist_tracks=max_artist_tracks,
            rules=rules,
            description=desc,
            settings=request.app.state.cfg,
        )
    except Exception as err:
        logger.warning(
            "Playlist generation with bounds failed (%s); trying standard similarity",
            err,
        )
        playlist = generate_playlist(
            db_path=request.app.state.db_path,
            name=name or "Audiophile Vibe Session",
            seed_track_id=parsed_seed_id,
            cluster_id=parsed_cluster_id,
            vibe=parsed_vibe,
            arc=parsed_arc,
            limit=limit,
            max_artist_tracks=max_artist_tracks,
            description=desc,
            settings=request.app.state.cfg,
        )

    transitions = calculate_transition_metrics(playlist.tracks)
    summary = calculate_playlist_summary(playlist.tracks, transitions)

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="components/playlist_builder.html",
        context={
            "playlist": playlist,
            "transitions": transitions,
            "summary": summary,
            "active_step": 3,
        },
    )


@router.get("/api/playlist/builder/search")
async def api_playlist_builder_search(
    request: Request,
    q: str = Query("", description="Search term for tracks"),
) -> Response:
    """Search tracks with acoustic telemetry for the seed track selector."""
    search_term = q.strip()
    with get_connection(request.app.state.db_path) as conn:
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
        results.append(
            {
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
            }
        )

    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(content={"results": results, "count": len(results)})

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="components/playlist_seed_results.html",
        context={
            "results": results,
            "query": search_term,
        },
    )


@router.post("/api/playlist/builder/preview")
async def api_playlist_builder_preview(
    request: Request,
    seed_track_id: int = Form(...),
    arc: str = Form("energy_ramp"),
    limit: int = Form(12),
    max_bpm_delta: float = Form(10.0),
    max_artist_tracks: int = Form(2),
    allow_half_double_time: bool = Form(False),
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
        allow_half_double_time=allow_half_double_time,
        vibe=parsed_vibe,
    )

    playlist = generate_playlist(
        db_path=request.app.state.db_path,
        name=name.strip() or "Harmonic Journey",
        seed_track_id=seed_track_id,
        arc=parsed_arc,
        vibe=parsed_vibe,
        limit=limit,
        max_artist_tracks=max_artist_tracks,
        rules=rules,
        settings=request.app.state.cfg,
    )

    transitions = calculate_transition_metrics(
        playlist.tracks,
        allow_half_double_time=allow_half_double_time,
    )
    summary = calculate_playlist_summary(playlist.tracks, transitions)

    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header or request.query_params.get("format") == "json":
        return JSONResponse(
            content={
                "playlist": playlist.to_dict(),
                "transitions": transitions,
                "summary": summary,
            }
        )

    return request.app.state.templates.TemplateResponse(
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


@router.post("/api/playlist/builder/reorder")
async def api_playlist_builder_reorder(
    request: Request,
    track_ids: str = Form(...),
    playlist_id: int | None = Form(None),
    step: int = Form(4),
) -> Response:
    """Reorder tracks in playlist, update database, and recalculate harmonic transitions."""
    ordered_ids = [int(x.strip()) for x in track_ids.split(",") if x.strip().isdigit()]
    if not ordered_ids:
        raise HTTPException(status_code=400, detail="Invalid track_ids")

    with get_connection(request.app.state.db_path) as conn:
        if playlist_id:
            pl_row = get_playlist(conn, playlist_id)
            if not pl_row:
                raise HTTPException(status_code=404, detail="Playlist not found")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
            add_tracks_to_playlist(conn, playlist_id, ordered_ids)

    if playlist_id:
        reordered_playlist = load_saved_playlist(request.app.state.db_path, playlist_id)
    else:
        with get_connection(request.app.state.db_path) as conn:
            all_tracks = {t["track_id"]: dict(t) for t in get_tracks_with_features(conn)}
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
        return JSONResponse(
            content={
                "playlist": reordered_playlist.to_dict(),
                "transitions": transitions,
                "summary": summary,
            }
        )

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="components/playlist_builder.html",
        context={
            "playlist": reordered_playlist,
            "transitions": transitions,
            "summary": summary,
            "active_step": step,
        },
    )


@router.post("/api/playlist/reorder", response_class=HTMLResponse)
async def api_reorder_playlist(
    request: Request,
    playlist_id: int = Form(...),
    track_ids: str = Form(...),
) -> Response:
    """Reorder tracks in playlist, update database, recalculate transitions."""
    ordered_ids = [int(x.strip()) for x in track_ids.split(",") if x.strip().isdigit()]
    if not ordered_ids:
        raise HTTPException(status_code=400, detail="Invalid track_ids")

    with get_connection(request.app.state.db_path) as conn:
        pl_row = get_playlist(conn, playlist_id)
        if not pl_row:
            raise HTTPException(status_code=404, detail="Playlist not found")

        cursor = conn.cursor()
        cursor.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        add_tracks_to_playlist(conn, playlist_id, ordered_ids)

    reordered_playlist = load_saved_playlist(request.app.state.db_path, playlist_id)
    if reordered_playlist is None:
        raise HTTPException(status_code=404, detail="Failed to reload reordered playlist")

    transitions = calculate_transition_metrics(reordered_playlist.tracks)
    summary = calculate_playlist_summary(reordered_playlist.tracks, transitions)

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="components/playlist_builder.html",
        context={
            "playlist": reordered_playlist,
            "transitions": transitions,
            "summary": summary,
            "active_step": 4,
        },
    )


@router.post("/api/playlist/save")
async def api_playlist_save(
    request: Request,
    name: str = Form(...),
    vibe_arc: str = Form(None),
    track_ids_json: str = Form(...),
) -> Response:
    """Save a playlist to the saved_playlists table."""
    try:
        import json

        track_ids = json.loads(track_ids_json)
        with get_connection(request.app.state.db_path) as conn:
            playlist_id = save_playlist(conn, name, vibe_arc, track_ids)
        return JSONResponse({"status": "success", "playlist_id": playlist_id})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


@router.post("/api/playlist/import")
async def api_playlist_import(request: Request) -> Response:
    """Parse an uploaded M3U8 file and save a new playlist."""
    form = await request.form()
    file = form.get("file")
    if not file or not hasattr(file, "filename"):
        raise HTTPException(status_code=400, detail="No file provided")

    content = (await file.read()).decode("utf-8")

    tracks = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tracks.append(line)

    with get_connection(request.app.state.db_path) as conn:
        cursor = conn.cursor()
        track_ids = []
        for track_path in tracks:
            cursor.execute("SELECT id FROM tracks WHERE path = ? OR path LIKE ?", (track_path, f"%{track_path}%"))
            row = cursor.fetchone()
            if row:
                track_ids.append(row["id"])

        if not track_ids:
            return JSONResponse({"status": "error", "message": "No matching tracks found"}, status_code=400)

        name = file.filename.replace(".m3u8", "").replace(".m3u", "")
        playlist_id = save_playlist(conn, name, "imported", track_ids)

    return JSONResponse({"status": "success", "playlist_id": playlist_id, "matched_tracks": len(track_ids)})


@router.delete("/api/playlist/{playlist_id}")
async def api_playlist_delete(request: Request, playlist_id: int) -> Response:
    """Remove a saved playlist."""
    with get_connection(request.app.state.db_path) as conn:
        success = delete_saved_playlist(conn, playlist_id)
        if success:
            return JSONResponse({"status": "success"})
        else:
            raise HTTPException(status_code=404, detail="Playlist not found")


@router.get("/api/playlist/{playlist_id}/export")
async def api_export_m3u8(request: Request, playlist_id: int) -> Response:
    """Download playlist as standard UTF-8 extended M3U8 file."""
    with get_connection(request.app.state.db_path) as conn:
        pl_row = get_playlist(conn, playlist_id)
        if not pl_row:
            raise HTTPException(status_code=404, detail="Playlist not found")
        tracks = get_playlist_tracks(conn, playlist_id)

    lines = ["#EXTM3U\n"]
    for t in tracks:
        duration_sec = int(round(float(t["duration"]))) if t["duration"] is not None else -1
        artist = t["artist"] or "Unknown Artist"
        title = t["title"] or "Unknown Title"
        lines.append(f"#EXTINF:{duration_sec},{artist} - {title}\n")
        lines.append(f"{t['path']}\n")

    safe_name = "".join(c for c in pl_row["name"] if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
    filename = f"{safe_name or 'playlist'}_{playlist_id}.m3u8"

    return Response(
        content="".join(lines),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
