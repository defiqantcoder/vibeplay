import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/plugins")
async def api_plugins_list() -> JSONResponse:
    """List registered add-ons and their enabled/initialization states."""
    from vibeplay.plugins.base import get_plugin_registry
    from vibeplay.plugins.dsp import DSPPlugin
    from vibeplay.plugins.maintenance import MaintenancePlugin

    reg = get_plugin_registry()
    if not reg.get("dsp"):
        reg.register(DSPPlugin())
    if not reg.get("maintenance"):
        reg.register(MaintenancePlugin())
    return JSONResponse(content={"plugins": reg.list_plugins()})


@router.post("/api/plugins/toggle")
async def api_plugins_toggle(request: Request) -> JSONResponse:
    """Toggle an add-on plugin enabled/disabled state."""
    from vibeplay.plugins.base import get_plugin_registry
    from vibeplay.plugins.dsp import DSPPlugin
    from vibeplay.plugins.maintenance import MaintenancePlugin

    try:
        body = await request.json()
        plugin_name = body.get("name")
        reg = get_plugin_registry()
        if not reg.get("dsp"):
            reg.register(DSPPlugin())
        if not reg.get("maintenance"):
            reg.register(MaintenancePlugin())
        p = reg.get(plugin_name)
        if not p:
            return JSONResponse(status_code=404, content={"error": f"Plugin '{plugin_name}' not found"})
        if p.is_enabled:
            p.disable()
        else:
            p.enable()
        return JSONResponse(content={"name": p.name, "enabled": p.is_enabled})
    except Exception as err:
        return JSONResponse(status_code=500, content={"error": str(err)})


@router.get("/api/plugins/list")
async def api_plugins_list_v2(request: Request) -> JSONResponse:
    pm = getattr(request.app.state, "plugin_manager", None)
    if not pm:
        return JSONResponse(status_code=500, content={"error": "Plugin manager not initialized"})
    return JSONResponse(content={"plugins": pm.list_plugins()})


@router.post("/api/plugins/{plugin_id}/toggle")
async def api_plugins_toggle_v2(plugin_id: str, request: Request) -> JSONResponse:
    pm = getattr(request.app.state, "plugin_manager", None)
    if not pm:
        return JSONResponse(status_code=500, content={"error": "Plugin manager not initialized"})

    try:
        data = await request.json()
        enable = data.get("enable", False)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    success = pm.toggle_plugin(plugin_id, enable)
    if success:
        return JSONResponse(content={"status": "ok", "plugin_id": plugin_id, "enabled": enable})
    return JSONResponse(status_code=400, content={"error": f"Failed to toggle plugin {plugin_id}"})
