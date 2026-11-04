"""Exercise desktop migration scripts against isolated source files."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_script(tmp_path, script):
    subprocess.run([sys.executable, str(ROOT / script)], cwd=tmp_path, check=True)


def write_desktop(tmp_path, name, content):
    path = tmp_path / "src" / "vibeplay" / "desktop" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def imported_names(content):
    return [
        alias.name
        for node in ast.parse(content).body
        if isinstance(node, ast.ImportFrom) and node.module == "vibeplay.desktop.app"
        for alias in node.names
        if alias.asname in (None, alias.name)
    ]


def test_migrations_preserve_already_migrated_files(tmp_path):
    paths = {}
    for name in ("app.py", "runner.py", "__main__.py"):
        paths[name] = write_desktop(tmp_path, name, (ROOT / "src/vibeplay/desktop" / name).read_text())
    originals = {name: path.read_text() for name, path in paths.items()}
    for script in ("patch_circular.py", "patch_main.py", "patch_runner.py"):
        run_script(tmp_path, script)
        run_script(tmp_path, script)
    assert {name: path.read_text() for name, path in paths.items()} == originals


@pytest.mark.parametrize("existing", [True, False])
def test_circular_migration_inserts_icon_resolver_once(tmp_path, existing):
    app = write_desktop(
        tmp_path, "app.py",
        "from pathlib import Path\n\n" + ("def resolve_app_icon_path():\n    return 'existing'\n\n" if existing else "")
        + "def setup_logging():\n    pass\n",
    )
    runner = write_desktop(tmp_path, "runner.py", "from vibeplay.desktop.app import run_webview, setup_gtk\n")
    run_script(tmp_path, "patch_circular.py")
    first = (app.read_text(), runner.read_text())
    run_script(tmp_path, "patch_circular.py")
    assert (app.read_text(), runner.read_text()) == first
    definitions = [node for node in ast.parse(first[0]).body if isinstance(node, ast.FunctionDef) and node.name == "resolve_app_icon_path"]
    assert len(definitions) == 1
    if existing:
        assert "return 'existing'" in first[0]
    assert imported_names(first[1]).count("resolve_app_icon_path") == 1


@pytest.mark.parametrize("existing", [True, False])
def test_main_migration_preserves_or_inserts_suppressed_import(tmp_path, existing):
    app_import = "from vibeplay.desktop.app import (\n    setup_logging,\n)  # noqa: E402\n" if existing else ""
    main = write_desktop(tmp_path, "__main__.py", app_import + "from vibeplay.desktop.runner import DesktopRunner\n")
    run_script(tmp_path, "patch_main.py")
    first = main.read_text()
    run_script(tmp_path, "patch_main.py")
    assert main.read_text() == first
    assert imported_names(first).count("setup_logging") == 1
    assert (app_import if existing else "from vibeplay.desktop.app import setup_logging  # noqa: E402\n") in first


@pytest.mark.parametrize("existing", ["", "setup_gtk", "run_webview", "run_webview, setup_gtk"])
def test_runner_migration_adds_only_missing_imports(tmp_path, existing):
    app_import = f"from vibeplay.desktop.app import {existing}\n" if existing else ""
    runner = write_desktop(tmp_path, "runner.py", app_import + "from vibeplay.desktop.security import is_loopback_host, validate_loopback_host\n")
    run_script(tmp_path, "patch_runner.py")
    first = runner.read_text()
    run_script(tmp_path, "patch_runner.py")
    assert runner.read_text() == first
    assert first.startswith(app_import)
    names = imported_names(first)
    assert names.count("setup_gtk") == 1
    assert names.count("run_webview") == 1
