"""Unit tests for Phase 0 desktop foundation, environment inspection, and UI data models."""

from __future__ import annotations

import socket

import pytest

from vibeplay.desktop.constants import (
    DEFAULT_BACKEND_HOST,
    DEFAULT_BACKEND_PORT,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_TITLE,
)
from vibeplay.desktop.environment import (
    DesktopEnvironment,
    find_free_loopback_port,
    generate_ephemeral_session_token,
    inspect_desktop_environment,
)
from vibeplay.ui.menu import build_desktop_menu_bar
from vibeplay.ui.theme import (
    THEME_PRESETS,
    get_available_themes,
    get_theme_by_id,
    get_theme_css_variables,
)


def test_desktop_constants() -> None:
    """Verify window geometry and backend networking constants."""
    assert DEFAULT_WINDOW_WIDTH >= 1024
    assert DEFAULT_WINDOW_HEIGHT >= 600
    assert DEFAULT_BACKEND_HOST == "127.0.0.1"
    assert DEFAULT_BACKEND_PORT == 8000
    assert "Audiophile" in WINDOW_TITLE


def test_inspect_desktop_environment() -> None:
    """Verify desktop environment inspection executes and returns valid DesktopEnvironment."""
    env = inspect_desktop_environment()
    assert isinstance(env, DesktopEnvironment)
    assert env.os_release != ""
    assert env.display_server in ("X11", "Wayland", "None (Headless)")
    assert isinstance(env.has_display, bool)
    assert isinstance(env.has_pywebview, bool)


def test_find_free_loopback_port_success() -> None:
    """Verify free loopback port discovery binds and returns available port."""
    port = find_free_loopback_port(preferred_port=8000, host="127.0.0.1")
    assert port >= 8000

    # Ensure returned port is actually bindable
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))


def test_find_free_loopback_port_collision_fallback() -> None:
    """Verify that when preferred port is occupied, it dynamically increments to next port."""
    # Temporarily bind 8000 to simulate another running process
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied_socket:
        occupied_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            occupied_socket.bind(("127.0.0.1", 8000))
            occupied_socket.listen(1)
            port = find_free_loopback_port(preferred_port=8000, host="127.0.0.1")
            assert port > 8000
        except OSError:
            # If 8000 was already occupied by another service, find_free_loopback_port should still succeed
            port = find_free_loopback_port(preferred_port=8000, host="127.0.0.1")
            assert port >= 8000


def test_generate_ephemeral_session_token() -> None:
    """Verify session token is cryptographically random and non-empty."""
    tok1 = generate_ephemeral_session_token()
    tok2 = generate_ephemeral_session_token()
    assert len(tok1) >= 32
    assert tok1 != tok2


def test_build_desktop_menu_bar_structure() -> None:
    """Verify menu bar sections and required Phase 2 keyboard shortcuts."""
    menu = build_desktop_menu_bar()
    section_ids = [s.id for s in menu]
    assert "file" in section_ids
    assert "edit" in section_ids
    assert "library" in section_ids
    assert "playback" in section_ids
    assert "dsp" in section_ids
    assert "view" in section_ids
    assert "help" in section_ids

    # Verify shortcuts
    file_section = next(s for s in menu if s.id == "file")
    shortcuts = {item.shortcut: item.id for item in file_section.items if item.shortcut}
    assert "Ctrl+O" in shortcuts
    assert "Ctrl+R" in shortcuts
    assert "Ctrl+," in shortcuts
    assert "Ctrl+Q" in shortcuts


def test_theme_presets_and_css_variables() -> None:
    """Verify all 5 required theme palettes from Desktop App Plan Phase 4 are available."""
    themes = get_available_themes()
    theme_ids = [t.id for t in themes]

    assert "god-of-ink" in theme_ids
    assert "wine" in theme_ids
    assert "obsidian" in theme_ids
    assert "swimming-with-the-whales" in theme_ids
    assert "mint-city" in theme_ids

    # Verify CSS variable declarations
    css = get_theme_css_variables("god-of-ink")
    assert "--bg-base" in css
    assert "--primary" in css
    assert "--status-ok" in css
    assert "--status-err" in css

    # Fallback to default theme on unknown id
    fallback = get_theme_by_id("nonexistent-theme")
    assert fallback.id == "god-of-ink"


def test_find_free_loopback_port_rejects_non_loopback() -> None:
    """Verify that find_free_loopback_port raises ValueError if non-loopback address is supplied."""
    with pytest.raises(ValueError, match="Security guardrail"):
        find_free_loopback_port(host="192.168.1.100")

    with pytest.raises(ValueError, match="Security guardrail"):
        find_free_loopback_port(host="0.0.0.0")


def test_find_free_loopback_port_exhausted() -> None:
    """Verify that find_free_loopback_port raises RuntimeError when max attempts are exhausted."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied.bind(("127.0.0.1", 9990))
        occupied.listen(1)
        with pytest.raises(RuntimeError, match="Unable to find a free loopback port"):
            find_free_loopback_port(preferred_port=9990, host="127.0.0.1", max_attempts=1)
