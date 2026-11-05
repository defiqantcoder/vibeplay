"""Player and hardware audio routing router for vibeplay."""

from __future__ import annotations

import html
import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from vibeplay.config import get_settings
from vibeplay.desktop.settings import update_desktop_settings
from vibeplay.player import (
    get_active_output_profile,
    get_output_profiles,
    get_playback_status,
    set_output_profile,
    set_volume,
    step_volume,
    toggle_mute,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/player", tags=["player"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/output/profiles")
async def api_get_output_profiles() -> JSONResponse:
    """Return dynamically probed audio output profiles (USB DACs & hardware sinks) and active route."""
    cfg = get_settings()
    return JSONResponse(
        content={
            "status": "ok",
            "active_profile": get_active_output_profile(cfg),
            "profiles": get_output_profiles(cfg),
        }
    )


@router.post("/output", response_class=HTMLResponse)
async def api_post_output(request: Request, profile: str | None = Form(None)) -> Response:
    """Switch hardware audio output profile, commit sink, and return updated output_switcher.html snippet with checkmark."""
    cfg = get_settings()
    target_profile = profile

    if not target_profile:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    target_profile = body.get("profile")
            except Exception:
                pass
    if not target_profile:
        target_profile = request.query_params.get("profile")
    if not target_profile:
        target_profile = "pure-bitperfect"

    try:
        # Commit hardware sink routing
        set_output_profile(str(target_profile), settings=cfg)

        # Dispatch to DSP IPC if applicable
        p_low = str(target_profile).lower()
        try:
            from vibe_dsp.ipc import DSPClient

            prof_map = {
                "pure-bitperfect": "pure-bitperfect",
                "pure bit-perfect (direct alsa)": "pure-bitperfect",
                "spatial-headphones": "spatial-headphones",
                "7.1.4 spatial headphones (sofa 3d)": "spatial-headphones",
                "receiver-passthrough": "receiver-passthrough",
                "av receiver passthrough (hdmi)": "receiver-passthrough",
                "pipewire sound server": "pure-bitperfect",
            }
            target_id = prof_map.get(p_low, str(target_profile))
            DSPClient().set_profile(target_id)
        except Exception as err:
            logger.debug("Could not dispatch profile to vibe-dsp IPC: %s", err)

        # Synchronize desktop settings
        if "spatial" in p_low:
            try:
                from vibe_dsp.spatial import set_spatial_virtualization_mode
                set_spatial_virtualization_mode("spatial_binaural")
                update_desktop_settings({"spatial_enabled": True, "spatial_mode": "3d_binaural", "dsp_profile": "spatial-headphones"})
            except Exception:
                pass
        elif "receiver" in p_low or "hdmi" in p_low:
            try:
                update_desktop_settings({"dsp_profile": "receiver-passthrough"})
            except Exception:
                pass
        elif "bit-perfect" in p_low or "pure" in p_low or "letshuoer" in p_low or "fiio" in p_low:
            try:
                from vibe_dsp.spatial import set_spatial_virtualization_mode
                set_spatial_virtualization_mode("stereo_direct")
                update_desktop_settings({"spatial_enabled": False, "spatial_mode": "stereo_direct", "dsp_profile": "pure-bitperfect"})
            except Exception:
                pass

        # Retrieve live playback status with the newly activated profile
        playback = get_playback_status(cfg.db_path, cfg)
        safe_target_profile = html.escape(str(target_profile))
        playback["active_profile"] = safe_target_profile
        playback["output_profile"] = safe_target_profile
        playback["output_profiles"] = get_output_profiles(cfg)

        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.query_params.get("format") == "json":
            return JSONResponse(
                content={
                    "status": "ok",
                    "active_profile": safe_target_profile,
                    "playback": playback,
                }
            )

        # Render updated output_switcher.html snippet with active checkmark class
        output_switcher_html = templates.get_template("components/output_switcher.html").render(
            request=request,
            playback=playback,
            popover_open=True,
        )
        transport_bar_html = templates.get_template("components/transport_bar.html").render(
            request=request,
            playback=playback,
        )

        return templates.TemplateResponse(
            request=request,
            name="components/output_switcher_response.html",
            context={
                "output_switcher_html": output_switcher_html,
                "transport_bar_html": transport_bar_html,
                "active_profile": safe_target_profile,
            },
        )
    except Exception as err:
        logger.error("Failed to set output profile %s: %s", target_profile, err, exc_info=True)
        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.query_params.get("format") == "json":
            return JSONResponse(status_code=500, content={"status": "error", "message": "Failed to set output profile"})
        return HTMLResponse(status_code=500, content="<div class='text-red-500'>Failed to set output profile</div>")


@router.post("/volume", response_class=HTMLResponse)
async def api_post_volume(request: Request, volume: int = Form(...)) -> Response:
    """Set playback volume (0-100) debounced from hardware controls or UI slider."""
    cfg = get_settings()
    res = set_volume(volume, settings=cfg)
    playback = get_playback_status(cfg.db_path, cfg)
    if "volume" in res:
        playback["volume"] = res["volume"]

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(content={"status": "ok", "volume": playback.get("volume")})

    return templates.TemplateResponse(
        request=request,
        name="components/transport_bar.html",
        context={"playback": playback},
    )


@router.post("/volume-step", response_class=HTMLResponse)
async def api_post_volume_step(request: Request, delta: int = Form(...)) -> Response:
    """Step playback volume up or down."""
    cfg = get_settings()
    res = step_volume(delta, settings=cfg)
    playback = get_playback_status(cfg.db_path, cfg)
    if "volume" in res:
        playback["volume"] = res["volume"]

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(content={"status": "ok", "volume": playback.get("volume")})

    return templates.TemplateResponse(
        request=request,
        name="components/transport_bar.html",
        context={"playback": playback},
    )


@router.post("/mute-toggle", response_class=HTMLResponse)
async def api_post_mute_toggle(request: Request) -> Response:
    """Toggle mute on/off."""
    cfg = get_settings()
    res = toggle_mute(settings=cfg)
    playback = get_playback_status(cfg.db_path, cfg)
    if "volume" in res:
        playback["volume"] = res["volume"]

    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse(content={"status": "ok", "volume": playback.get("volume")})

    return templates.TemplateResponse(
        request=request,
        name="components/transport_bar.html",
        context={"playback": playback},
    )
