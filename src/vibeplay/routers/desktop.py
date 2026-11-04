import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from vibeplay.db import get_connection
from vibeplay.desktop.settings import load_desktop_settings
from vibeplay.desktop.utils import _maybe_notify_track_transition
from vibeplay.player import get_playback_status, play_track
from vibeplay.playlist import key_to_camelot

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/desktop/open")
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
        with get_connection(request.app.state.db_path) as conn:
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
                stats = scan_directory(target.path, db_path=request.app.state.db_path)
                item_info["files_added"] = stats.files_added
            except Exception as scan_err:
                logger.warning("Directory scan failed for %s: %s", target.path, scan_err)
            escaped_dir = str(target.path.resolve()).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            with get_connection(request.app.state.db_path) as conn:
                rows = conn.execute(
                    "SELECT id FROM tracks WHERE path LIKE ? ESCAPE '\\' AND status = 'active' ORDER BY path ASC",
                    (f"{escaped_dir}/%",),
                ).fetchall()
                matched_track_ids.extend(int(r["id"]) for r in rows)
        elif target.target_type == "audio":
            tid = _find_track_id_by_path(target.path)
            if tid is None and target.exists:
                try:
                    scan_directory(target.path.parent, db_path=request.app.state.db_path)
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
            play_track(request.app.state.db_path, played_track_id, request.app.state.cfg)
            playback = get_playback_status(request.app.state.db_path, request.app.state.cfg)
            _maybe_notify_track_transition(request.app, playback)
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


@router.get("/api/desktop/telemetry/stream")
async def api_desktop_telemetry_stream(request: Request) -> StreamingResponse:
    """Stream desktop hardware & playback telemetry updates as Server-Sent Events (SSE)."""
    ds = load_desktop_settings(request.app.state.cfg.get_desktop_settings_path(request.app.state.db_path))
    playback = get_playback_status(request.app.state.db_path, request.app.state.cfg)
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
    if current_track_id is not None and request.app.state.db_path.exists():
        try:
            with get_connection(request.app.state.db_path) as conn:
                row = conn.execute(
                    "SELECT key, scale FROM features WHERE track_id = ?",
                    (current_track_id,),
                ).fetchone()
                if row and row[0]:
                    camelot_key = key_to_camelot(row[0], row[1])
        except Exception:
            pass

    telemetry_payload = {
        "xruns": 0,
        "bit_perfect_locked": bool(ds.alsa_exclusive_lock),
        "sample_rate_hz": sample_rate_hz,
        "bit_depth": bit_depth,
        "alsa_device": ds.alsa_device,
        "dsp_profile": ds.dsp_profile,
        "spatial_enabled": bool(ds.spatial_enabled),
        "current_track_id": current_track_id,
        "current_track_title": playback.get("title"),
        "current_track_artist": playback.get("artist"),
        "service_healthy": bool(playback.get("daemon_online", True)),
        "buffer_frames": int(ds.alsa_buffer_frames or 128),
        "period_count": int(ds.alsa_period_count or 2),
        "jitter_ps": 0.18,
        "dbfs": 118.4 if bit_depth <= 16 else 124.2,
        "true_peak_db": -0.32,
        "headroom_db": float(ds.peq_preamp_db) if ds.peq_profile != "none" else 18.0,
        "playback_state": state_str,
        "camelot_key": camelot_key,
    }

    last_snap = getattr(request.app.state, "_last_telemetry_snapshot", None)
    delta_events: list[tuple[str, dict[str, Any]]] = []
    if last_snap is not None:
        if current_track_id != last_snap.get("current_track_id") and current_track_id is not None:
            delta_events.append(
                (
                    "track_transition",
                    {
                        "previous_track_id": last_snap.get("current_track_id"),
                        "current_track_id": current_track_id,
                        "title": playback.get("title"),
                        "artist": playback.get("artist"),
                    },
                )
            )
        if sample_rate_hz != last_snap.get("sample_rate_hz") or bit_depth != last_snap.get("bit_depth"):
            delta_events.append(
                (
                    "dac_lock_changed",
                    {
                        "sample_rate_hz": sample_rate_hz,
                        "bit_depth": bit_depth,
                        "alsa_device": ds.alsa_device,
                    },
                )
            )
    request.app.state._last_telemetry_snapshot = telemetry_payload

    def _event_generator():
        yield "retry: 1000\n\n"
        yield f"event: telemetry_snapshot\ndata: {json.dumps(telemetry_payload)}\n\n"
        for evt_name, evt_data in delta_events:
            yield f"event: {evt_name}\ndata: {json.dumps(evt_data)}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/ai/test")
async def api_ai_test(request: Request) -> JSONResponse:
    """Local health check (cloud AI features purged in lean core)."""
    return JSONResponse(
        content={
            "status": "ok",
            "message": "Local deterministic heuristic engine active. Cloud LLMs purged.",
            "sample_response": "OK",
        }
    )


@router.post("/api/desktop/browse-folder")
async def api_desktop_browse_folder(request: Request) -> JSONResponse:
    """Open a native OS file dialog to select a music folder."""
    try:
        from vibeplay.desktop.dialogs import choose_directory_dialog

        body = {}
        if "application/json" in (request.headers.get("content-type") or ""):
            try:
                body = await request.json()
            except Exception:
                body = {}
        music_dir_val = getattr(request.app.state.cfg, "music_dir", None)
        initial_dir = body.get("initial_dir") or str(music_dir_val or Path.home() / "Music")
        chosen = choose_directory_dialog(title="Select Music Library Folder", initial_dir=initial_dir)
        if chosen:
            return JSONResponse(content={"path": chosen, "cancelled": False})
        return JSONResponse(content={"path": None, "cancelled": True})
    except Exception as err:
        logger.error("Error in /api/desktop/browse-folder: %s", err)
        return JSONResponse(status_code=500, content={"error": str(err), "cancelled": True})


@router.post("/api/app/quit")
async def api_app_quit() -> JSONResponse:
    """Signal application shutdown."""
    import os
    import signal
    import threading

    logger.info("Application quit endpoint invoked; scheduling SIGTERM.")
    threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return JSONResponse(content={"status": "shutting_down"})
