import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from vibeplay.desktop.settings import DesktopSettings, load_desktop_settings, save_desktop_settings
from vibeplay.player import set_output_profile

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/menu")
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


@router.get("/api/themes")
async def api_get_themes(request: Request) -> JSONResponse:
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


@router.get("/api/settings")
async def api_get_settings(request: Request) -> JSONResponse:
    """Return persisted desktop & hardware settings and available PEQ presets."""
    current = load_desktop_settings(request.app.state.cfg.get_desktop_settings_path(request.app.state.db_path))
    peq_presets: list[str] = []
    try:
        from vibe_dsp.peq import list_available_presets

        raw_presets = list_available_presets()
        peq_presets = [(p["name"] if isinstance(p, dict) else str(p)) for p in raw_presets]
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
            "settings_path": str(request.app.state.cfg.get_desktop_settings_path(request.app.state.db_path)),
        }
    )


@router.post("/api/settings")
@router.put("/api/settings")
async def api_update_settings(request: Request) -> JSONResponse:
    """Validate, apply, and persist partial or full desktop settings updates without reload."""

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

    current = load_desktop_settings(request.app.state.cfg.get_desktop_settings_path(request.app.state.db_path))
    merged = current.model_dump()
    merged.update(payload)

    # Synchronize spatial_enabled <-> spatial_mode when only one is supplied
    if "spatial_enabled" in payload and "spatial_mode" not in payload:
        merged["spatial_mode"] = "3d_binaural" if bool(payload["spatial_enabled"]) else "stereo_direct"
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
    if ("peq_profile" in payload or "peq_preamp_auto" in payload) and "peq_preamp_db" not in payload and validated.peq_preamp_auto:
        if validated.peq_profile == "none":
            validated.peq_preamp_db = 0.0
        else:
            try:
                from vibe_dsp.peq import lookup_autoeq_model

                prof = lookup_autoeq_model(validated.peq_profile, allow_network=False)
                if prof is not None:
                    validated.peq_preamp_db = round(float(prof.calculated_preamp), 2)
                else:
                    validated.peq_preamp_db = -5.5
            except Exception:
                validated.peq_preamp_db = -5.5

    save_desktop_settings(validated, request.app.state.cfg.get_desktop_settings_path(request.app.state.db_path))

    cfg = request.app.state.cfg
    ds = validated
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

    # Best-effort live application to DSP / audio transport
    if "spatial_enabled" in payload or "spatial_mode" in payload:
        try:
            from vibe_dsp.spatial import set_spatial_virtualization_mode

            mode = "spatial_binaural" if validated.spatial_enabled else "stereo_direct"
            set_spatial_virtualization_mode(mode)
            if validated.spatial_enabled:
                set_output_profile("7.1.4 Spatial Headphones (SOFA 3D)", settings=request.app.state.cfg)
        except Exception:
            pass

    if "dsp_profile" in payload:
        try:
            from vibe_dsp.ipc import DSPClient

            DSPClient().set_profile(validated.dsp_profile)
            set_output_profile(validated.dsp_profile, settings=request.app.state.cfg)
        except Exception:
            set_output_profile(validated.dsp_profile, settings=request.app.state.cfg)

    return JSONResponse(
        content={
            "status": "saved",
            "settings": validated.model_dump(mode="json"),
        }
    )
