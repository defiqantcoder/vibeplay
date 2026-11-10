"""Root and application shell router for vibeplay."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from vibeplay.config import DEFAULT_DESKTOP_SETTINGS_PATH, get_settings
from vibeplay.desktop.settings import DesktopSettings, load_desktop_settings
from vibeplay.player import get_output_profiles, get_playback_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["root"])

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


def safe_load_desktop_settings(path: Path | None = None) -> DesktopSettings:
    """Safely load desktop settings without raising uncaught exceptions if missing."""
    try:
        return load_desktop_settings(path)
    except Exception as err:
        logger.warning("Could not read desktop settings (%s); falling back to defaults", err)
        return DesktopSettings()


@router.get("/api/desktop/settings-dialog", response_class=HTMLResponse)
async def api_desktop_settings_dialog(request: Request) -> Response:
    """Return Settings Dialog modal snippet safely."""
    ds = safe_load_desktop_settings()
    peq_presets: list[str] = []
    try:
        from vibe_dsp.peq import list_available_presets

        peq_presets = [(p["name"] if isinstance(p, dict) else str(p)) for p in list_available_presets()]
    except Exception:
        peq_presets = ["7hz_zero_2", "apple_airpods_pro_2", "moondrop_blessing_2", "sennheiser_hd600"]

    return templates.TemplateResponse(
        request=request,
        name="components/settings_dialog.html",
        context={
            "desktop_settings": ds,
            "peq_presets": peq_presets,
            "settings_path": str(DEFAULT_DESKTOP_SETTINGS_PATH),
        },
    )


@router.get("/api/desktop/output-switcher", response_class=HTMLResponse)
async def api_desktop_output_switcher(request: Request) -> Response:
    """Return Output Switcher popover snippet with dynamically detected DACs."""
    cfg = get_settings()
    playback = get_playback_status(cfg.db_path, cfg)
    playback["output_profiles"] = get_output_profiles(cfg)

    return templates.TemplateResponse(
        request=request,
        name="components/output_switcher.html",
        context={
            "playback": playback,
            "popover_open": True,
        },
    )
