"""Tests for Phase 5: PyInstaller Bundling for Ubuntu 24.04 LTS."""

from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibeplay import __version__
from vibeplay.analysis.essentia_analyzer import EssentiaAnalyzer
from vibeplay.config import Settings
from vibeplay.db import init_db
from vibeplay.desktop.packaging import (
    BUNDLE_ENTRYPOINT,
    BUNDLE_NAME,
    REQUIRED_DSP_PROFILES,
    REQUIRED_STATIC_FILES,
    REQUIRED_TEMPLATE_FILES,
    collect_pyinstaller_datas,
    get_bundle_root,
    is_frozen_bundle,
    resolve_dsp_profiles_dir,
    resolve_models_dir,
    resolve_static_dir,
    resolve_templates_dir,
    verify_bundle_assets,
)
from vibeplay.web import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "packaging" / "vibeplay.spec"


def test_vibeplay_spec_exists_and_executes_cleanly(monkeypatch: pytest.MonkeyPatch):
    """Verify packaging/vibeplay.spec exists, parses, and builds Analysis/PYZ/EXE objects."""
    assert SPEC_PATH.is_file(), "packaging/vibeplay.spec must exist"

    # Execute spec in default onefile mode
    monkeypatch.delenv("VIBEPLAY_BUNDLE_MODE", raising=False)
    ns_onefile = runpy.run_path(str(SPEC_PATH))
    assert "a" in ns_onefile
    assert "pyz" in ns_onefile
    assert "exe" in ns_onefile
    assert "coll" not in ns_onefile

    analysis_obj = ns_onefile["a"]
    exe_obj = ns_onefile["exe"]
    assert Path(analysis_obj.scripts[0]).resolve() == (REPO_ROOT / BUNDLE_ENTRYPOINT).resolve()
    assert exe_obj.kwargs["name"] == BUNDLE_NAME
    assert exe_obj.kwargs["console"] is False
    assert exe_obj.kwargs["upx"] is False

    # Execute spec in onedir mode
    monkeypatch.setenv("VIBEPLAY_BUNDLE_MODE", "onedir")
    ns_onedir = runpy.run_path(str(SPEC_PATH))
    assert "exe" in ns_onedir
    assert "coll" in ns_onedir
    assert ns_onedir["exe"].kwargs["exclude_binaries"] is True
    assert ns_onedir["coll"].kwargs["name"] == BUNDLE_NAME


def test_spec_bundles_required_datas_hiddenimports_and_excludes():
    """Verify templates, static assets, DSP profiles, GTK/WebKit2 hooks, and dev exclusions."""
    ns = runpy.run_path(str(SPEC_PATH))
    analysis_obj = ns["a"]

    datas_dict = {dest: Path(src) for src, dest in analysis_obj.datas}
    assert "vibeplay/templates" in datas_dict
    assert datas_dict["vibeplay/templates"].is_dir()
    assert "vibeplay/static" in datas_dict
    assert datas_dict["vibeplay/static"].is_dir()

    hidden = set(analysis_obj.kwargs["hiddenimports"])
    for req_mod in (
        "vibeplay.web",
        "vibeplay.desktop.runner",
        "vibe_dsp.peq",
        "vibe_dsp.spatial",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "webview.platforms.gtk",
        "gi",
        "gi.repository.Gtk",
        "gi.repository.WebKit2",
    ):
        assert req_mod in hidden, f"Missing required hiddenimport: {req_mod}"

    gi_hooks = analysis_obj.kwargs["hooksconfig"]["gi"]
    assert gi_hooks["module-versions"]["Gtk"] == "3.0"
    assert gi_hooks["module-versions"]["WebKit2"] == "4.1"

    excludes = set(analysis_obj.kwargs["excludes"])
    for forbidden in (
        "pytest",
        "pytest_cov",
        "coverage",
        "mypy",
        "ruff",
        "uv_build",
        "pip",
        "wheel",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "wx",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
    ):
        assert forbidden in excludes, f"Dev/unused module '{forbidden}' must be excluded"


def test_collect_pyinstaller_datas_includes_optional_models_and_hrtf(tmp_path: Path):
    """Verify collect_pyinstaller_datas bundles models/*.pb and packaging/hrtf/*.sofa when present."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "src/vibeplay/templates").mkdir(parents=True)
    (fake_repo / "src/vibeplay/static").mkdir(parents=True)
    (fake_repo / "src/vibe_dsp/profiles").mkdir(parents=True)
    models_dir = fake_repo / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "discogs-effnet-bs64-1.pb").write_bytes(b"protobuf-weights")

    hrtf_dir = fake_repo / "packaging" / "hrtf"
    hrtf_dir.mkdir(parents=True)
    (hrtf_dir / "kemar.sofa").write_bytes(b"sofa-hrtf")

    datas = dict((dest, src) for src, dest in collect_pyinstaller_datas(fake_repo))
    assert "vibeplay/templates" in datas
    assert "vibeplay/static" in datas
    assert "models" in datas
    assert "vibe_dsp/hrtf" in datas


def test_verify_bundle_assets_in_source_mode():
    """Verify all required templates, static files, and DSP profiles exist in source tree."""
    report = verify_bundle_assets()
    assert report.is_frozen is False
    assert report.is_valid is True
    assert report.missing_assets == []
    for tpl in REQUIRED_TEMPLATE_FILES:
        assert (report.templates_dir / tpl).is_file()
    for st in REQUIRED_STATIC_FILES:
        assert (report.static_dir / st).is_file()
    for prof in REQUIRED_DSP_PROFILES:
        assert (report.dsp_profiles_dir / prof).is_file()


def test_frozen_meipass_simulation_no_relative_path_assumptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Simulate a frozen PyInstaller executable running from an empty CWD and verify all assets resolve."""
    fake_meipass = tmp_path / "_MEI99999"
    shutil.copytree(REPO_ROOT / "src/vibeplay/templates", fake_meipass / "vibeplay/templates")
    shutil.copytree(REPO_ROOT / "src/vibeplay/static", fake_meipass / "vibeplay/static")
    (fake_meipass / "vibe_dsp/profiles").mkdir(parents=True)
    (fake_meipass / "models").mkdir(parents=True)
    (fake_meipass / "models" / "discogs-effnet-bs64-1.pb").write_bytes(b"dummy-pb")

    # Change CWD to an empty directory outside the repo to catch any relative path assumptions
    empty_cwd = tmp_path / "empty_working_dir"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    monkeypatch.delenv("VIBEPLAY_MODELS_DIR", raising=False)

    assert is_frozen_bundle() is True
    assert get_bundle_root() == fake_meipass.resolve()
    assert resolve_templates_dir() == (fake_meipass / "vibeplay/templates").resolve()
    assert resolve_static_dir() == (fake_meipass / "vibeplay/static").resolve()
    assert resolve_dsp_profiles_dir() == (fake_meipass / "vibe_dsp/profiles").resolve()
    assert resolve_models_dir() == (fake_meipass / "models").resolve()

    report = verify_bundle_assets()
    assert report.is_frozen is True
    assert report.is_valid is True
    assert report.missing_assets == []

    # Verify EssentiaAnalyzer and Settings resolve frozen models_dir without CWD assumptions
    analyzer = EssentiaAnalyzer()
    assert analyzer.models_dir == (fake_meipass / "models").resolve()

    db_file = tmp_path / "frozen_test.db"
    settings_file = tmp_path / "desktop_settings.json"
    init_db(db_file)
    cfg = Settings(db_path=db_file, desktop_settings_path=settings_file)
    assert cfg.models_dir == (fake_meipass / "models").resolve()

    # Verify FastAPI app serves templates and static files from _MEIPASS
    app = create_app(db_path=db_file, settings=cfg)
    client = TestClient(app)

    index_res = client.get("/")
    assert index_res.status_code == 200
    assert "VIBEPLAY" in index_res.text

    css_res = client.get("/static/style.css")
    assert css_res.status_code == 200
    assert "--bg-surface" in css_res.text

    htmx_res = client.get("/static/htmx.min.js")
    assert htmx_res.status_code == 200


def test_verify_bundle_assets_detects_missing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify verify_bundle_assets reports missing files when a bundle is incomplete."""
    incomplete_meipass = tmp_path / "_MEI_INCOMPLETE"
    (incomplete_meipass / "vibeplay/templates").mkdir(parents=True)
    (incomplete_meipass / "vibeplay/static").mkdir(parents=True)
    (incomplete_meipass / "vibe_dsp/profiles").mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(incomplete_meipass), raising=False)

    report = verify_bundle_assets()
    assert report.is_valid is False
    assert "templates/base.html" in report.missing_assets
    assert "static/style.css" in report.missing_assets


def test_local_binary_entrypoint_launches_without_uv_run(tmp_path: Path):
    """Verify the installed vibeplay-desktop binary launches directly without `uv run` from any CWD."""
    venv_bin = REPO_ROOT / ".venv" / "bin" / "vibeplay-desktop"
    assert venv_bin.is_file(), f"Expected installed entrypoint binary at {venv_bin}"

    ver_proc = subprocess.run(
        [str(venv_bin), "--version"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert ver_proc.returncode == 0
    assert f"vibeplay-desktop {__version__}" in ver_proc.stdout

    help_proc = subprocess.run(
        [str(venv_bin), "--help"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert help_proc.returncode == 0
    assert "--headless" in help_proc.stdout
    assert "--no-mpd" in help_proc.stdout
