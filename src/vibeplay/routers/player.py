"""Player and hardware audio routing router for vibeplay."""

from __future__ import annotations

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
        available_profiles = get_output_profiles(cfg)
        target_str = str(target_profile).strip()
        matched_profile = None

        # 1. Match against dynamically discovered profiles
        for p in available_profiles:
            p_name = p["name"] if isinstance(p, dict) else str(p)
            p_id = str(p.get("id", "")) if isinstance(p, dict) else ""
            if target_str.lower() == p_name.lower() or (p_id and target_str == p_id):
                matched_profile = p_name
                break

        # 2. Match against canonical profile aliases if not matched yet
        if not matched_profile:
            canonical_map = {
                "pure-bitperfect": "Pure Bit-Perfect (Direct ALSA)",
                "pure bit-perfect (direct alsa)": "Pure Bit-Perfect (Direct ALSA)",
                "spatial-headphones": "7.1.4 Spatial Headphones (SOFA 3D)",
                "7.1.4 spatial headphones (sofa 3d)": "7.1.4 Spatial Headphones (SOFA 3D)",
                "receiver-passthrough": "AV Receiver Passthrough (HDMI)",
                "av receiver passthrough (hdmi)": "AV Receiver Passthrough (HDMI)",
                "pipewire sound server": "PipeWire Sound Server",
                "pipewire": "PipeWire Sound Server",
            }
            matched_profile = canonical_map.get(target_str.lower())

        # 3. Fallback safely to bit-perfect default if unallowlisted input
        safe_profile = matched_profile or "Pure Bit-Perfect (Direct ALSA)"

        # Commit hardware sink routing using validated display name
        set_output_profile(safe_profile, settings=cfg)

        # Dispatch to DSP IPC if applicable
        p_low = safe_profile.lower()
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
            target_id = prof_map.get(p_low, safe_profile)
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
        playback["active_profile"] = safe_profile
        playback["output_profile"] = safe_profile
        playback["output_profiles"] = available_profiles

        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.query_params.get("format") == "json":
            return JSONResponse(
                content={
                    "status": "ok",
                    "active_profile": safe_profile,
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
                "active_profile": safe_profile,
            },
        )
    except Exception:
        logger.exception("Error setting output profile")
        return JSONResponse(status_code=500, content={"status": "error", "message": "Failed to set profile"})


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


def build_router(cfg, resolved_db_path, templates, settings_file_path, _sync_runtime_cfg):
    """Bind the original web handlers to this application's state."""
    from vibeplay.player import adjust_volume_step, set_volume_level

    router = APIRouter(prefix="/api/player", tags=["player"])

    @router.post("/volume", response_class=HTMLResponse)
    async def api_player_volume(request: Request, volume: int = Form(...)) -> Response:
        """Set volume level [0-100]."""
        set_volume_level(volume, cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        playback["volume"] = max(0, min(100, volume))
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @router.post("/volume-step", response_class=HTMLResponse)
    async def api_player_volume_step(request: Request, delta: int = 5) -> Response:
        """Adjust volume level by delta (positive or negative) within [0, 100]."""
        step_val = delta
        try:
            form = await request.form()
            if "delta" in form:
                step_val = int(form["delta"])
        except Exception:
            pass
        if "delta" in request.query_params:
            try:
                step_val = int(request.query_params["delta"])
            except Exception:
                pass

        res = adjust_volume_step(step_val, cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        if "volume" in res:
            try:
                playback["volume"] = int(res["volume"])
            except (ValueError, TypeError):
                pass
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @router.post("/mute-toggle", response_class=HTMLResponse)
    async def api_player_mute_toggle(request: Request) -> Response:
        """Toggle mute/unmute state."""
        res = toggle_mute(cfg)
        playback = get_playback_status(resolved_db_path, cfg)
        if "volume" in res:
            try:
                playback["volume"] = int(res["volume"])
            except (ValueError, TypeError):
                pass
        return templates.TemplateResponse(
            request=request,
            name="components/transport_bar.html",
            context={
                "playback": playback,
            },
        )

    @router.get("/output/profiles")
    async def api_player_output_profiles() -> JSONResponse:
        """Return list of dynamic audio output profiles and current active profile."""
        from vibeplay.player import (
            get_active_output_profile,
            get_dynamic_output_profiles,
        )

        return JSONResponse(
            content={
                "status": "ok",
                "active_profile": get_active_output_profile(cfg),
                "profiles": get_dynamic_output_profiles(cfg),
            }
        )

    @router.post("/output", response_class=HTMLResponse)
    async def api_player_output(request: Request, profile: str | None = Form(None)) -> Response:
        """Switch audio hardware output profile and notify vibe-dsp IPC engine."""
        target_profile = profile
        if not target_profile:
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = await request.json()
                    target_profile = body.get("profile")
                except Exception:
                    pass
        if not target_profile:
            target_profile = request.query_params.get("profile")
        from vibeplay.player import get_output_profiles

        available_profiles = get_output_profiles(cfg)
        target_str = str(target_profile or "").strip()
        matched_profile: str | None = None

        for p in available_profiles:
            p_name = p["name"] if isinstance(p, dict) else str(p)
            p_id = str(p.get("id", "")) if isinstance(p, dict) else ""
            if target_str.lower() == p_name.lower() or (p_id and target_str == p_id):
                matched_profile = p_name
                break

        if not matched_profile:
            alias_map = {
                "pure-bitperfect": "pure-bitperfect",
                "pure bit-perfect (direct alsa)": "Pure Bit-Perfect (Direct ALSA)",
                "spatial-headphones": "spatial-headphones",
                "7.1.4 spatial headphones (sofa 3d)": "7.1.4 Spatial Headphones (SOFA 3D)",
                "receiver-passthrough": "receiver-passthrough",
                "av receiver passthrough (hdmi)": "AV Receiver Passthrough (HDMI)",
                "pipewire sound server": "PipeWire Sound Server",
                "pipewire": "PipeWire Sound Server",
                "usb dac (bit-perfect)": "USB DAC (Bit-Perfect)",
                "direct alsa (hw:0,0)": "Direct ALSA (hw:0,0)",
                "headphones": "Headphones",
            }
            matched_profile = alias_map.get(target_str.lower())

        target_profile = matched_profile or "Pure Bit-Perfect (Direct ALSA)"

        set_output_profile(target_profile, settings=cfg)
        try:
            from vibe_dsp.ipc import DSPClient

            dsp_map = {
                "pure-bitperfect": "pure-bitperfect",
                "spatial-headphones": "spatial-headphones",
                "receiver-passthrough": "receiver-passthrough",
                "Pure Bit-Perfect (Direct ALSA)": "pure-bitperfect",
                "7.1.4 Spatial Headphones (SOFA 3D)": "spatial-headphones",
                "AV Receiver Passthrough (HDMI)": "receiver-passthrough",
                "USB DAC (Bit-Perfect)": "pure-bitperfect",
                "Direct ALSA (hw:0,0)": "pure-bitperfect",
                "Headphones": "spatial-headphones",
                "PipeWire Sound Server": "pure-bitperfect",
            }
            target_id = dsp_map.get(target_profile, "pure-bitperfect")
            client = DSPClient()
            client.set_profile(target_id)
        except Exception as err:
            logger.debug("Could not dispatch profile switch to vibe-dsp IPC: %s", err)

        # Synchronize spatial state and desktop settings
        p_low = target_profile.lower()
        if "spatial" in p_low:
            try:
                from vibe_dsp.spatial import set_spatial_virtualization_mode

                set_spatial_virtualization_mode("spatial_binaural")
                update_desktop_settings(
                    {
                        "spatial_enabled": True,
                        "spatial_mode": "3d_binaural",
                        "dsp_profile": "spatial-headphones",
                    },
                    settings_file_path,
                )
            except Exception:
                pass
        elif "receiver" in p_low or "hdmi" in p_low:
            try:
                update_desktop_settings(
                    {"dsp_profile": "receiver-passthrough"},
                    settings_file_path,
                )
            except Exception:
                pass
        elif "bit-perfect" in p_low or "pure" in p_low or "letshuoer" in p_low:
            try:
                from vibe_dsp.spatial import set_spatial_virtualization_mode

                set_spatial_virtualization_mode("stereo_direct")
                update_desktop_settings(
                    {
                        "spatial_enabled": False,
                        "spatial_mode": "stereo_direct",
                        "dsp_profile": "pure-bitperfect",
                    },
                    settings_file_path,
                )
            except Exception:
                pass

        playback = get_playback_status(resolved_db_path, cfg)
        playback["active_profile"] = target_profile
        playback["output_profile"] = target_profile
        from vibeplay.player import get_output_profiles

        playback["output_profiles"] = get_output_profiles(cfg)

        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.query_params.get("format") == "json":
            return JSONResponse(
                content={
                    "status": "ok",
                    "active_profile": target_profile,
                    "playback": playback,
                }
            )

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
                "active_profile": str(target_profile),
            },
        )

    return router
