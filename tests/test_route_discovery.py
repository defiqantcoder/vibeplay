"""Route discovery must tolerate unrelated and computed decorators."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '''
def create_app():
    @other
    @app.get("/valid")
    @app.post("/alias")
    async def valid(): pass

    @app.middleware("http")
    def middleware(): pass

    @app.get()
    def no_args(): pass

    @app.get(PATH)
    def dynamic(): pass

    @app.get(prefix + "/dynamic")
    def computed(): pass

    @app.get(factory())
    def called(): pass

    @factory().get("/nested")
    def nested(): pass

    @pkg.app.get("/attribute")
    def attribute(): pass
'''


def prepare_source(tmp_path, monkeypatch):
    path = tmp_path / "src/vibeplay/web.py"
    path.parent.mkdir(parents=True)
    path.write_text(SOURCE)
    monkeypatch.chdir(tmp_path)


def test_route_visitor_filters_non_routes(tmp_path, monkeypatch):
    prepare_source(tmp_path, monkeypatch)
    result = runpy.run_path(str(ROOT / "parse_routes.py"))
    assert result["visitor"].routes == [("/valid", "valid", "get"), ("/alias", "valid", "post")]


def test_second_visitor_handles_missing_and_dynamic_arguments(tmp_path, monkeypatch):
    prepare_source(tmp_path, monkeypatch)
    result = runpy.run_path(str(ROOT / "parse_routes2.py"))
    assert ("", "no_args", "get") in result["visitor"].routes
    assert ("/valid", "valid", "get") in result["visitor"].routes


def test_split_report_matches_stacked_route_decorators(tmp_path, monkeypatch):
    prepare_source(tmp_path, monkeypatch)
    result = runpy.run_path(str(ROOT / "split_script.py"))
    assert [(node.name, path) for node, path in result["route_defs"]] == [
        ("valid", "/valid"), ("valid", "/alias")
    ]


def test_extraction_mounts_handlers_and_is_repeatable(tmp_path):
    root = tmp_path / "vibeplay"
    routers = root / "routers"
    routers.mkdir(parents=True)
    (root / "web.py").write_text('''
def create_app():
    @app.post("/api/player/volume", response_class=HTMLResponse)
    async def volume(value: int = 5):
        return cfg, value
    @app.get("/api/settings")
    @app.get("/api/settings/alias")
    async def settings():
        return settings_file_path
    app.include_router(library_router)
''')
    (routers / "player.py").write_text('''
@router.post("/volume")
async def volume(): pass
''')
    (routers / "settings.py").write_text('''
@router.get("/api/settings")
@router.get("/api/settings/alias")
async def settings(): pass
''')
    extract = runpy.run_path(str(ROOT / "plan_extraction.py"))["extract_routes"]
    extract(root)
    contents = {p: p.read_text() for p in root.rglob("*.py")}
    assert "@app.post" not in contents[root / "web.py"]
    assert "app.include_router(build_player_router" in contents[root / "web.py"]
    assert "app.include_router(build_settings_router" in contents[root / "web.py"]
    assert "return cfg, value" in contents[routers / "player.py"]
    assert "return settings_file_path" in contents[routers / "settings.py"]
    extract(root)
    assert contents == {p: p.read_text() for p in contents}
