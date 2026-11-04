"""Desktop application setup and initialization phase."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from vibeplay.desktop.constants import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_MIN_HEIGHT,
    DEFAULT_WINDOW_MIN_WIDTH,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_TITLE,
)

logger = logging.getLogger(__name__)


def resolve_app_icon_path() -> Path | None:
    """Locate the VibePlay application icon file for window decoration."""
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        for p in (
            meipass / "packaging" / "icons" / "vibeplay.svg",
            meipass / "vibeplay.svg",
            meipass / "vibeplay" / "static" / "vibeplay.svg",
        ):
            if p.is_file():
                return p

    user_icon = Path("~/.local/share/icons/hicolor/scalable/apps/vibeplay.svg").expanduser()
    if user_icon.is_file():
        return user_icon

    system_icon = Path("/usr/share/icons/hicolor/scalable/apps/vibeplay.svg")
    if system_icon.is_file():
        return system_icon

    repo_icon = Path(__file__).resolve().parent.parent.parent.parent / "packaging" / "icons" / "vibeplay.svg"
    if repo_icon.is_file():
        return repo_icon

    pkg_icon = Path(__file__).resolve().parent.parent / "static" / "vibeplay.svg"
    if pkg_icon.is_file():
        return pkg_icon

    return None


def setup_logging(debug: bool = False) -> None:
    """Configure basic application logging."""
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def setup_gtk() -> None:
    """Configure GTK application identity and icons."""
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        GLib.set_prgname("vibeplay")
        GLib.set_application_name("VibePlay")
        icon_file = resolve_app_icon_path()
        if icon_file and icon_file.is_file():
            try:
                Gtk.Window.set_default_icon_from_file(str(icon_file))
            except Exception:
                pass
        Gtk.Window.set_default_icon_name("vibeplay")
    except Exception as err:
        logger.debug("Could not apply GTK app icon attributes: %s", err)


def run_webview(host: str, port: int) -> Any:
    """Initialize and run the PyWebView window.

    Args:
        host: Host loopback address.
        port: TCP port for backend server.

    Returns:
        The created webview window instance.
    """
    try:
        import webview

        url = f"http://{host}:{port}/"
        window = webview.create_window(
            title=WINDOW_TITLE,
            url=url,
            width=DEFAULT_WINDOW_WIDTH,
            height=DEFAULT_WINDOW_HEIGHT,
            min_size=(DEFAULT_WINDOW_MIN_WIDTH, DEFAULT_WINDOW_MIN_HEIGHT),
            text_select=True,
        )
        webview.start()
        return window
    except Exception as err:
        logger.error("PyWebView GUI failure: %s", err)
        return None
