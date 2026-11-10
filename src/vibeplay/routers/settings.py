"""Settings router for vibeplay desktop and hardware audio preferences."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from vibeplay.desktop.settings import (
    DEFAULT_DESKTOP_SETTINGS_PATH,
    DesktopSettings,
    load_desktop_settings,
    save_desktop_settings,
    update_desktop_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def safe_get_setting(settings_obj: Any, key: str, default: Any = "") -> Any:
    """Safely retrieve configuration key without raising KeyError or AttributeError.

    Supports dictionary, DesktopSettings, Pydantic BaseModel, or None.
    """
    if settings_obj is None:
        return default
    if isinstance(settings_obj, dict):
        return settings_obj.get(key, default)
    if hasattr(settings_obj, "get") and callable(settings_obj.get):
        try:
            return settings_obj.get(key, default)
        except Exception:
            pass
    return getattr(settings_obj, key, default)


def safe_load_settings(path: Path | None = None) -> DesktopSettings:
    """Load desktop settings with guaranteed fallback to empty defaults on missing/corrupt file."""
    try:
        return load_desktop_settings(path)
    except Exception as err:
        logger.warning("Error loading desktop settings from %s (%s); returning defaults", path, err)
        return DesktopSettings()


@router.get("/api/settings")
async def api_get_settings(request: Request) -> Response:
    """Return persisted desktop & hardware settings, with safe fallback and modal HTML support."""
    current = safe_load_settings()

    # If caller specifically requests HTML or HTMX modal snippet
    accept_hdr = request.headers.get("accept", "")
    is_htmx = bool(request.headers.get("hx-request"))
    view_modal = request.query_params.get("view") == "modal" or request.query_params.get("format") == "html"

    if (view_modal or is_htmx or "text/html" in accept_hdr) and "application/json" not in accept_hdr:
        try:
            from vibe_dsp.peq import list_available_presets

            peq_presets = [(p["name"] if isinstance(p, dict) else str(p)) for p in list_available_presets()]
        except Exception:
            peq_presets = ["7hz_zero_2", "apple_airpods_pro_2", "moondrop_blessing_2", "sennheiser_hd600"]

        return templates.TemplateResponse(
            request=request,
            name="components/settings_dialog.html",
            context={
                "desktop_settings": current,
                "peq_presets": peq_presets,
                "settings_path": str(DEFAULT_DESKTOP_SETTINGS_PATH),
            },
        )

    # Standard JSON payload
    peq_presets_list: list[str] = []
    try:
        from vibe_dsp.peq import list_available_presets

        raw_presets = list_available_presets()
        peq_presets_list = [(p["name"] if isinstance(p, dict) else str(p)) for p in raw_presets]
    except Exception:
        peq_presets_list = [
            "7hz_zero_2",
            "apple_airpods_pro_2",
            "moondrop_blessing_2",
            "sennheiser_hd600",
        ]

    settings_dict = current.model_dump(mode="json")
    # Guarantee safe access to crucial external keys
    settings_dict["gemini_api_key"] = safe_get_setting(current, "gemini_api_key", "")
    settings_dict["gemini_model"] = safe_get_setting(current, "gemini_model", "gemini-3.8-flash")

    return JSONResponse(
        content={
            "settings": settings_dict,
            "peq_presets": peq_presets_list,
            "settings_path": str(DEFAULT_DESKTOP_SETTINGS_PATH),
        }
    )


@router.get("/api/settings/modal", response_class=HTMLResponse)
async def api_get_settings_modal(request: Request) -> Response:
    """Return the rendered HTML snippet of the Settings Dialog so webview does not abort."""
    current = safe_load_settings()
    try:
        from vibe_dsp.peq import list_available_presets

        peq_presets = [(p["name"] if isinstance(p, dict) else str(p)) for p in list_available_presets()]
    except Exception:
        peq_presets = ["7hz_zero_2", "apple_airpods_pro_2", "moondrop_blessing_2", "sennheiser_hd600"]

    return templates.TemplateResponse(
        request=request,
        name="components/settings_dialog.html",
        context={
            "desktop_settings": current,
            "peq_presets": peq_presets,
            "settings_path": str(DEFAULT_DESKTOP_SETTINGS_PATH),
        },
    )


@router.get("/api/settings/gemini")
@router.get("/api/settings/api-key")
async def api_get_gemini_key() -> JSONResponse:
    """Safely query Gemini API configuration without KeyError or AttributeError."""
    current = safe_load_settings()
    return JSONResponse(
        content={
            "gemini_api_key": safe_get_setting(current, "gemini_api_key", ""),
            "gemini_model": safe_get_setting(current, "gemini_model", "gemini-3.8-flash"),
            "llm_provider": safe_get_setting(current, "llm_provider", "gemini"),
        }
    )


@router.post("/api/settings/gemini")
@router.post("/api/settings/api-key")
async def api_save_gemini_key(request: Request) -> JSONResponse:
    """Safely save or update Gemini API key and model tier."""
    api_key = ""
    model = "gemini-3.8-flash"
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                api_key = str(body.get("gemini_api_key") or body.get("api_key") or "").strip()
                model = str(body.get("gemini_model") or body.get("model") or "gemini-3.8-flash").strip()
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            api_key = str(form.get("gemini_api_key") or form.get("api_key") or "").strip()
            model = str(form.get("gemini_model") or form.get("model") or "gemini-3.8-flash").strip()
        except Exception:
            pass

    updates = {"gemini_api_key": api_key, "gemini_model": model, "llm_provider": "gemini"}
    try:
        updated = update_desktop_settings(updates)
        return JSONResponse(
            content={
                "status": "ok",
                "has_gemini_api_key": bool(safe_get_setting(updated, "gemini_api_key", "")),
                "gemini_api_key": "",
                "gemini_model": safe_get_setting(updated, "gemini_model", "gemini-3.8-flash"),
            }
        )
    except Exception as err:
        logger.error("Request failed: %s", err, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Could not persist Gemini settings."},
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
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid JSON body."},
            )
    else:
        try:
            form = await request.form()
            payload = dict(form)
        except Exception:
            payload = dict(request.query_params)

    current = safe_load_settings()
    merged = current.model_dump()
    merged.update(payload)

    # Safe upgrade of legacy Gemini models if passed
    if "gemini_model" in merged:
        m = str(merged["gemini_model"]).strip()
        if m in {"gemini-2.5-flash", "gemini-1.5-flash", ""}:
            merged["gemini_model"] = "gemini-3.8-flash"
        elif m in {"gemini-2.5-pro", "gemini-1.5-pro"}:
            merged["gemini_model"] = "gemini-3-pro-preview"

    # Synchronize spatial_enabled <-> spatial_mode
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

    # Auto-compute negative headroom preamp when peq_profile changes
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

    try:
        save_desktop_settings(validated)
    except Exception as err:
        logger.error("Request failed: %s", err, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Could not update settings."},
        )

    return JSONResponse(
        content={
            "status": "saved",
            "settings": validated.model_dump(mode="json", exclude={"gemini_api_key"}),
        }
    )


def build_router(cfg, resolved_db_path, templates, settings_file_path, _sync_runtime_cfg):
    """Bind the original web handlers to this application's state."""
    from vibeplay.player import set_output_profile

    router = APIRouter(prefix='', tags=['settings'])

    @router.get("/api/settings")
    async def api_get_settings(request: Request) -> Response:
        """Return persisted desktop & hardware settings, with safe fallback and modal HTML support."""
        try:
            current = load_desktop_settings(settings_file_path)
        except Exception:
            current = DesktopSettings()

        accept_hdr = request.headers.get("accept", "")
        is_htmx = bool(request.headers.get("hx-request"))
        view_modal = request.query_params.get("view") == "modal" or request.query_params.get("format") == "html"

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

        if (view_modal or is_htmx or "text/html" in accept_hdr) and "application/json" not in accept_hdr:
            return templates.TemplateResponse(
                request=request,
                name="components/settings_dialog.html",
                context={
                    "desktop_settings": current,
                    "peq_presets": peq_presets,
                    "settings_path": str(settings_file_path),
                },
            )

        settings_dict = current.model_dump(mode="json") if hasattr(current, "model_dump") else {}
        settings_dict["gemini_api_key"] = current.get("gemini_api_key", "") if hasattr(current, "get") else getattr(current, "gemini_api_key", "")
        settings_dict["gemini_model"] = (
            current.get("gemini_model", "gemini-3.8-flash") if hasattr(current, "get") else getattr(current, "gemini_model", "gemini-3.8-flash")
        )  # noqa: E501

        return JSONResponse(
            content={
                "settings": settings_dict,
                "peq_presets": peq_presets,
                "settings_path": str(settings_file_path),
            }
        )


    @router.get("/api/settings/modal", response_class=HTMLResponse)
    async def api_settings_modal(request: Request) -> Response:
        """Return the Settings Dialog modal HTML snippet."""
        try:
            current = load_desktop_settings(settings_file_path)
        except Exception:
            current = DesktopSettings()
        try:
            from vibe_dsp.peq import list_available_presets

            peq_presets = [(p["name"] if isinstance(p, dict) else str(p)) for p in list_available_presets()]
        except Exception:
            peq_presets = ["7hz_zero_2", "apple_airpods_pro_2", "moondrop_blessing_2", "sennheiser_hd600"]
        return templates.TemplateResponse(
            request=request,
            name="components/settings_dialog.html",
            context={
                "desktop_settings": current,
                "peq_presets": peq_presets,
                "settings_path": str(settings_file_path),
            },
        )


    @router.get("/api/settings/gemini")
    @router.get("/api/settings/api-key")
    async def api_get_gemini_key() -> JSONResponse:
        """Safely query Gemini API configuration without KeyError or AttributeError."""
        try:
            current = load_desktop_settings(settings_file_path)
        except Exception:
            current = DesktopSettings()
        key = current.get("gemini_api_key", "") if hasattr(current, "get") else getattr(current, "gemini_api_key", "")
        model = current.get("gemini_model", "gemini-3.8-flash") if hasattr(current, "get") else getattr(current, "gemini_model", "gemini-3.8-flash")  # noqa: E501
        provider = current.get("llm_provider", "gemini") if hasattr(current, "get") else getattr(current, "llm_provider", "gemini")
        return JSONResponse(
            content={
                "gemini_api_key": key,
                "gemini_model": model,
                "llm_provider": provider,
            }
        )


    @router.post("/api/settings/gemini")
    @router.post("/api/settings/api-key")
    async def api_save_gemini_key(request: Request) -> JSONResponse:
        """Safely save or update Gemini API key and model tier."""
        api_key = ""
        model = "gemini-3.8-flash"
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    api_key = str(body.get("gemini_api_key") or body.get("api_key") or "").strip()
                    model = str(body.get("gemini_model") or body.get("model") or "gemini-3.8-flash").strip()
            except Exception:
                pass
        else:
            try:
                form = await request.form()
                api_key = str(form.get("gemini_api_key") or form.get("api_key") or "").strip()
                model = str(form.get("gemini_model") or form.get("model") or "gemini-3.8-flash").strip()
            except Exception:
                pass
        updates = {"gemini_api_key": api_key, "gemini_model": model, "llm_provider": "gemini"}
        try:
            updated = update_desktop_settings(updates, settings_file_path)
            _sync_runtime_cfg(updated)
            key = updated.get("gemini_api_key", "") if hasattr(updated, "get") else getattr(updated, "gemini_api_key", "")
            return JSONResponse(content={"status": "ok", "gemini_api_key": key, "gemini_model": model})
        except Exception as err:
            logger.error("Request failed: %s", err, exc_info=True)
            return JSONResponse(status_code=500, content={"status": "error", "message": "Operation failed"})


    @router.post("/api/settings")
    @router.put("/api/settings")
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
            except Exception:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid JSON body."},
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

        save_desktop_settings(validated, settings_file_path)
        _sync_runtime_cfg(validated)

        # Best-effort live application to DSP / audio transport
        if "spatial_enabled" in payload or "spatial_mode" in payload:
            try:
                from vibe_dsp.spatial import set_spatial_virtualization_mode

                mode = "spatial_binaural" if validated.spatial_enabled else "stereo_direct"
                set_spatial_virtualization_mode(mode)
                if validated.spatial_enabled:
                    set_output_profile("7.1.4 Spatial Headphones (SOFA 3D)", settings=cfg)
            except Exception:
                pass

        if "dsp_profile" in payload:
            try:
                from vibe_dsp.ipc import DSPClient

                DSPClient().set_profile(validated.dsp_profile)
                set_output_profile(validated.dsp_profile, settings=cfg)
            except Exception:
                set_output_profile(validated.dsp_profile, settings=cfg)

        return JSONResponse(
            content={
                "status": "saved",
                "settings": validated.model_dump(mode="json"),
            }
        )

    return router
