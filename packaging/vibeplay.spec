# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller Bundle Specification for vibeplay on Ubuntu 24.04 LTS (Noble Numbat).

Builds a self-contained `vibeplay-desktop` executable bundling:
- Python 3.12+ runtime & project packages (`vibeplay`, `vibe_dsp`)
- FastAPI web server & Uvicorn ASGI workers
- Jinja2 HTML templates (`src/vibeplay/templates/`)
- Static CSS/JS assets (`src/vibeplay/static/`)
- Transducer PEQ reference profiles (`src/vibe_dsp/profiles/`)
- Optional Essentia TensorFlow model weights (`models/*.pb`) and SOFA HRTF files
- PyWebView GTK3 / WebKit2GTK 4.1 bindings (`gi.repository.Gtk`, `gi.repository.WebKit2`)

Excludes dev/test tooling (`pytest`, `ruff`, `mypy`, `coverage`, `uv_build`) and
non-GTK GUI toolkits (`tkinter`, `PyQt5`, `PyQt6`, `PySide2`, `PySide6`, `wx`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Resolve repository and src directories whether invoked via PyInstaller (SPECPATH) or Python
_SPEC_DIR = Path(globals().get("SPECPATH", Path(__file__).resolve().parent)).resolve()
REPO_ROOT = _SPEC_DIR.parent
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from vibeplay.desktop.packaging import (  # noqa: E402
    BUNDLE_ENTRYPOINT,
    BUNDLE_EXCLUDES,
    BUNDLE_HIDDEN_IMPORTS,
    BUNDLE_NAME,
    collect_pyinstaller_datas,
)

block_cipher = None

ENTRYPOINT_SCRIPT = str(REPO_ROOT / BUNDLE_ENTRYPOINT)
BUNDLED_DATAS = collect_pyinstaller_datas(REPO_ROOT)
HIDDEN_IMPORTS = list(BUNDLE_HIDDEN_IMPORTS)
EXCLUDED_MODULES = list(BUNDLE_EXCLUDES)

# Allow fallback mocks when loaded outside PyInstaller's build runner (e.g., unit test validation)
if "Analysis" not in globals():

    class _SpecStub:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.pure = kwargs.get("pure", [])
            self.scripts = args[0] if args else []
            self.binaries = kwargs.get("binaries", [])
            self.datas = kwargs.get("datas", [])

    Analysis = _SpecStub  # type: ignore[misc,assignment]
    PYZ = _SpecStub  # type: ignore[misc,assignment]
    EXE = _SpecStub  # type: ignore[misc,assignment]
    COLLECT = _SpecStub  # type: ignore[misc,assignment]

a = Analysis(
    [ENTRYPOINT_SCRIPT],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=BUNDLED_DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita"],
            "themes": ["Adwaita"],
            "module-versions": {
                "Gtk": "3.0",
                "WebKit2": "4.1",
            },
        },
    },
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data if hasattr(a, "zipped_data") else None, cipher=block_cipher)

BUNDLE_MODE = os.environ.get("VIBEPLAY_BUNDLE_MODE", "onefile").strip().lower()

if BUNDLE_MODE == "onedir":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=BUNDLE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=BUNDLE_NAME,
    )
else:
    # Default: Self-contained single-file Ubuntu binary (`dist/vibeplay-desktop`)
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=BUNDLE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
