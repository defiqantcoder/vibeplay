"""Verify migrated handlers through the application's registered routes."""

from fastapi.routing import iter_route_contexts

from vibeplay.config import Settings
from vibeplay.web import create_app

EXPECTED_ROUTES = {
    "vibeplay.routers.player": {
        ("GET", "/api/player/output/profiles"),
        ("POST", "/api/player/output"),
        ("POST", "/api/player/volume"),
        ("POST", "/api/player/volume-step"),
        ("POST", "/api/player/mute-toggle"),
    },
    "vibeplay.routers.settings": {
        ("GET", "/api/settings"),
        ("GET", "/api/settings/modal"),
        ("GET", "/api/settings/gemini"),
        ("GET", "/api/settings/api-key"),
        ("POST", "/api/settings/gemini"),
        ("POST", "/api/settings/api-key"),
        ("POST", "/api/settings"),
        ("PUT", "/api/settings"),
    },
}


def test_routes_registered_by_create_app(tmp_path):
    app = create_app(settings=Settings(db_path=tmp_path / "migration.db"), api_key="")
    for module, expected in EXPECTED_ROUTES.items():
        for method, path in expected:
            matches = [
                route for route in iter_route_contexts(app.routes)
                if getattr(route, "path", None) == path and method in (route.methods or set())
            ]
            assert len(matches) == 1, (method, path, matches)
            assert matches[0].endpoint.__module__ == module, (method, path, matches[0].endpoint)


def test_settings_use_each_apps_file_and_runtime_config(tmp_path):
    from fastapi.testclient import TestClient

    clients = []
    configs = []
    for name in ("first", "second"):
        cfg = Settings(db_path=tmp_path / name / "library.db")
        configs.append(cfg)
        clients.append(TestClient(create_app(settings=cfg, api_key="")))
    response = clients[0].post("/api/settings", json={"analyzer_workers": 3})
    assert response.status_code == 200
    assert configs[0].analyzer_workers == 3
    assert clients[0].get("/api/settings").json()["settings"]["analyzer_workers"] == 3
    assert clients[1].get("/api/settings").json()["settings"]["analyzer_workers"] != 3


def test_volume_step_preserves_query_and_form_inputs(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import vibeplay.player
    import vibeplay.routers.player

    calls = []
    monkeypatch.setattr(vibeplay.player, "adjust_volume_step", lambda delta, cfg: calls.append(delta) or {"volume": 50})
    monkeypatch.setattr(vibeplay.routers.player, "get_playback_status", lambda *args: {})
    cfg = Settings(db_path=tmp_path / "library.db")
    client = TestClient(create_app(settings=cfg, api_key=""))
    assert client.post("/api/player/volume-step?delta=-3").status_code == 200
    assert client.post("/api/player/volume-step", data={"delta": "7"}).status_code == 200
    assert calls == [-3, 7]
