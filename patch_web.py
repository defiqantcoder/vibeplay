import sys

def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Find the end of `def create_app(...) -> FastAPI:` function
    target_str = "    return app"

    if target_str not in content:
        print("Target string not found!")
        return

    # Prepare our new endpoints and plugin initialization
    injection = """
    # -- Plugin Management Endpoints --
    from vibeplay.plugins.manager import get_plugin_manager
    plugin_mgr = get_plugin_manager(app)
    plugin_mgr.initialize()
    app.state.plugin_manager = plugin_mgr

    @app.get("/api/plugins/list")
    async def api_plugins_list() -> JSONResponse:
        pm = getattr(app.state, "plugin_manager", None)
        if not pm:
            return JSONResponse(status_code=500, content={"error": "Plugin manager not initialized"})
        return JSONResponse(content={"plugins": pm.list_plugins()})

    @app.post("/api/plugins/{plugin_id}/toggle")
    async def api_plugins_toggle(plugin_id: str, request: Request) -> JSONResponse:
        pm = getattr(app.state, "plugin_manager", None)
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

    return app
"""

    new_content = content.replace(target_str, injection.lstrip('\n'))

    with open(filepath, 'w') as f:
        f.write(new_content)

if __name__ == '__main__':
    patch_file('src/vibeplay/web.py')
