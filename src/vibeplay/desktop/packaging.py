"""PyInstaller frozen bundle path resolution and Ubuntu 24.04 packaging specification helpers."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

BUNDLE_NAME: str = "vibeplay-desktop"
BUNDLE_ENTRYPOINT: str = "src/vibeplay/desktop/__main__.py"

REQUIRED_TEMPLATE_FILES: tuple[str, ...] = (
    "base.html",
    "index.html",
    "components/cluster_cards.html",
    "components/desktop_chrome.html",
    "components/desktop_scripts.html",
    "components/library_table.html",
    "components/playlist_builder.html",
    "components/settings_dialog.html",
    "components/styles.html",
    "components/track_detail.html",
    "components/transport_bar.html",
)

REQUIRED_STATIC_FILES: tuple[str, ...] = (
    "style.css",
    "htmx.min.js",
)

REQUIRED_DSP_PROFILES: tuple[str, ...] = (
    "7hz_zero_2.txt",
    "apple_airpods_pro_2.txt",
    "moondrop_blessing_2.txt",
    "sennheiser_hd600.txt",
)

# Explicit data directories bundled into the PyInstaller archive: (repo_relative_src, bundle_dest)
BUNDLE_DATAS: tuple[tuple[str, str], ...] = (
    ("src/vibeplay/templates", "vibeplay/templates"),
    ("src/vibeplay/static", "vibeplay/static"),
    ("src/vibe_dsp/profiles", "vibe_dsp/profiles"),
)

# Hidden imports required for FastAPI/Uvicorn, Jinja2, PyWebView GTK3/WebKit2GTK on Ubuntu 24.04, and DSP
BUNDLE_HIDDEN_IMPORTS: tuple[str, ...] = (
    "vibeplay",
    "vibeplay.cli",
    "vibeplay.config",
    "vibeplay.db",
    "vibeplay.desktop",
    "vibeplay.desktop.__main__",
    "vibeplay.desktop.constants",
    "vibeplay.desktop.environment",
    "vibeplay.desktop.packaging",
    "vibeplay.desktop.settings",
    "vibeplay.desktop.supervisor",
    "vibeplay.duplicates",
    "vibeplay.enrichment",
    "vibeplay.exporter",
    "vibeplay.llm",
    "vibeplay.player",
    "vibeplay.playlist",
    "vibeplay.scanner",
    "vibeplay.ui",
    "vibeplay.ui.menu",
    "vibeplay.ui.theme",
    "vibeplay.vectors",
    "vibeplay.web",
    "vibeplay.analysis",
    "vibeplay.analysis.base",
    "vibeplay.analysis.essentia_analyzer",
    "vibeplay.analysis.librosa_analyzer",
    "vibe_dsp",
    "vibe_dsp.alsa_reservation",
    "vibe_dsp.backup",
    "vibe_dsp.cli",
    "vibe_dsp.hardware",
    "vibe_dsp.ipc",
    "vibe_dsp.latency",
    "vibe_dsp.models",
    "vibe_dsp.passthrough",
    "vibe_dsp.peq",
    "vibe_dsp.pipewire",
    "vibe_dsp.spatial",
    # FastAPI / Starlette / Uvicorn dynamic imports
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "multipart",
    "python_multipart",
    # Ubuntu 24.04 PyWebView + GTK3 + WebKit2GTK 4.1 bindings
    "webview",
    "webview.platforms.gtk",
    "gi",
    "gi.repository.Gtk",
    "gi.repository.Gdk",
    "gi.repository.GLib",
    "gi.repository.GObject",
    "gi.repository.Gio",
    "gi.repository.WebKit2",
)

# Dev dependencies, test runners, and unused GUI toolkits excluded from the Ubuntu binary
BUNDLE_EXCLUDES: tuple[str, ...] = (
    "pytest",
    "_pytest",
    "pytest_cov",
    "coverage",
    "mypy",
    "ruff",
    "uv_build",
    "pip",
    "wheel",
    "setuptools",
    "tkinter",
    "_tkinter",
    "turtle",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",
    "webview.platforms.qt",
    "webview.platforms.cef",
    "webview.platforms.winforms",
    "webview.platforms.cocoa",
    "webview.platforms.android",
    "webview.platforms.edgechromium",
    "webview.platforms.mshtml",
    "IPython",
    "ipykernel",
    "ipywidgets",
    "jupyter",
    "notebook",
    "matplotlib",
    "doctest",
    "pdb",
)


@dataclass(frozen=True)
class BundleAssetReport:
    """Verification report for packaged runtime assets."""

    is_frozen: bool
    bundle_root: Path
    templates_dir: Path
    static_dir: Path
    dsp_profiles_dir: Path
    models_dir: Path
    missing_assets: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True if all required templates, static files, and DSP profiles are present."""
        return len(self.missing_assets) == 0


def is_frozen_bundle() -> bool:
    """Return True when running inside a frozen PyInstaller executable (`sys._MEIPASS`)."""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def get_bundle_root() -> Path:
    """Return the root resource extraction directory when frozen, or the `src/` directory in source mode."""
    if is_frozen_bundle():
        meipass = getattr(sys, "_MEIPASS")
        return Path(meipass).resolve()
    return Path(__file__).resolve().parent.parent.parent


def resolve_package_resource(package: str, relative_path: str | Path) -> Path:
    """Resolve a resource path inside `package` safely for both frozen PyInstaller and normal runs.

    Args:
        package: Top-level Python package name (`'vibeplay'` or `'vibe_dsp'`).
        relative_path: Path relative to the package root (e.g., `'templates'`, `'static'`, `'profiles'`).

    Returns:
        Path: Absolute path to the resolved resource directory or file.
    """
    rel = Path(relative_path)
    root = get_bundle_root()

    # 1. Check <bundle_root>/<package>/<relative_path> (standard PyInstaller datas layout & src/ layout)
    candidate_pkg = root / package / rel
    if candidate_pkg.exists():
        return candidate_pkg.resolve()

    # 2. Check <bundle_root>/<relative_path> (flat PyInstaller datas fallback)
    candidate_flat = root / rel
    if candidate_flat.exists():
        return candidate_flat.resolve()

    # 3. Fallback to package directory relative to this module
    fallback = Path(__file__).resolve().parent.parent.parent / package / rel
    return fallback.resolve()


def resolve_templates_dir() -> Path:
    """Resolve the Jinja2 `templates` directory for both frozen and standard execution."""
    return resolve_package_resource("vibeplay", "templates")


def resolve_static_dir() -> Path:
    """Resolve the FastAPI `static` assets directory for both frozen and standard execution."""
    return resolve_package_resource("vibeplay", "static")


def resolve_dsp_profiles_dir() -> Path:
    """Resolve the bundled `vibe_dsp/profiles` directory for both frozen and standard execution."""
    return resolve_package_resource("vibe_dsp", "profiles")


def resolve_models_dir(explicit_dir: Path | None = None) -> Path:
    """Resolve the Essentia pretrained model weights directory without CWD-relative assumptions when frozen.

    Resolution order:
    1. Explicit `explicit_dir` argument if provided.
    2. `VIBEPLAY_MODELS_DIR` environment variable if set.
    3. When frozen (`sys._MEIPASS`): `<_MEIPASS>/models` or `<_MEIPASS>/vibeplay/models` if bundled,
       otherwise `~/.local/share/vibeplay/models`.
    4. In source mode: `<repo_root>/models` if it exists, or `~/.local/share/vibeplay/models` if it exists,
       defaulting to `<repo_root>/models`.
    """
    if explicit_dir is not None:
        return Path(explicit_dir).expanduser().resolve()

    env_dir = os.environ.get("VIBEPLAY_MODELS_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    xdg_models = Path("~/.local/share/vibeplay/models").expanduser()

    if is_frozen_bundle():
        root = get_bundle_root()
        for candidate in (root / "models", root / "vibeplay" / "models"):
            if candidate.exists():
                return candidate.resolve()
        return xdg_models.resolve()

    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    repo_models = repo_root / "models"
    if repo_models.exists():
        return repo_models.resolve()
    if xdg_models.exists():
        return xdg_models.resolve()
    return repo_models.resolve()


def collect_pyinstaller_datas(repo_root: Path | None = None) -> list[tuple[str, str]]:
    """Return the list of `(source_path, target_dir)` tuples for PyInstaller `Analysis(datas=...)`.

    Includes required templates, static assets, and DSP profiles, plus optional Essentia models
    and SOFA HRTF files if present on the build host.
    """
    base = (
        Path(repo_root).resolve()
        if repo_root is not None
        else Path(__file__).resolve().parent.parent.parent.parent
    )
    datas: list[tuple[str, str]] = []

    for src_rel, dest_dir in BUNDLE_DATAS:
        src_abs = base / src_rel
        if src_abs.exists():
            datas.append((str(src_abs), dest_dir))

    # Optional Essentia TensorFlow model weights (.pb / .json)
    models_dir = base / "models"
    if models_dir.is_dir():
        model_files = list(models_dir.glob("*.pb")) + list(models_dir.glob("*.json"))
        if model_files:
            datas.append((str(models_dir), "models"))

    # Optional default SOFA HRTF impulse files if present in packaging/hrtf or repo hrtf/
    hrtf_dir = base / "packaging" / "hrtf"
    if hrtf_dir.is_dir() and any(hrtf_dir.glob("*.sofa")):
        datas.append((str(hrtf_dir), "vibe_dsp/hrtf"))

    return datas


def verify_bundle_assets() -> BundleAssetReport:
    """Verify that all required Jinja2 templates, static assets, and DSP PEQ profiles exist."""
    templates_dir = resolve_templates_dir()
    static_dir = resolve_static_dir()
    dsp_profiles_dir = resolve_dsp_profiles_dir()
    models_dir = resolve_models_dir()

    missing: list[str] = []

    for rel_tpl in REQUIRED_TEMPLATE_FILES:
        tpl_path = templates_dir / rel_tpl
        if not tpl_path.is_file() or tpl_path.stat().st_size == 0:
            missing.append(f"templates/{rel_tpl}")

    for rel_static in REQUIRED_STATIC_FILES:
        st_path = static_dir / rel_static
        if not st_path.is_file() or st_path.stat().st_size == 0:
            missing.append(f"static/{rel_static}")

    for rel_prof in REQUIRED_DSP_PROFILES:
        prof_path = dsp_profiles_dir / rel_prof
        if not prof_path.is_file() or prof_path.stat().st_size == 0:
            missing.append(f"profiles/{rel_prof}")

    return BundleAssetReport(
        is_frozen=is_frozen_bundle(),
        bundle_root=get_bundle_root(),
        templates_dir=templates_dir,
        static_dir=static_dir,
        dsp_profiles_dir=dsp_profiles_dir,
        models_dir=models_dir,
        missing_assets=missing,
    )
