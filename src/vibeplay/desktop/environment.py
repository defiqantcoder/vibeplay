"""System, windowing, and runtime service environment inspection for vibeplay desktop."""

from __future__ import annotations

import logging
import os
import platform
import secrets
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibeplay.desktop.constants import (
    DEFAULT_BACKEND_HOST,
    DEFAULT_BACKEND_PORT,
    MAX_PORT_SEARCH_ATTEMPTS,
)
from vibeplay.desktop.security import validate_loopback_host

logger = logging.getLogger(__name__)


@dataclass
class DesktopEnvironment:
    """Detailed summary of operating system, display server, and desktop runtime readiness."""

    os_release: str
    desktop_session: str
    display_server: str
    has_display: bool
    has_gtk: bool
    has_webkit2: bool
    has_pywebview: bool
    mpd_status: str
    pipewire_status: str
    is_desktop_ready: bool
    details: dict[str, Any] = field(default_factory=dict)


def inspect_desktop_environment() -> DesktopEnvironment:
    """Inspect current Ubuntu OS, display environment, GTK/WebKit libraries, and audio daemons.

    Returns:
        DesktopEnvironment: Complete environment diagnostic report.
    """
    # 1. OS & Distribution Detection
    os_info = f"{platform.system()} {platform.release()}"
    try:
        os_release_path = Path("/etc/os-release")
        if os_release_path.exists():
            for line in os_release_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    os_info = line.split("=", 1)[1].strip().strip("\"'")
                    break
    except Exception as err:
        logger.debug("Could not read /etc/os-release: %s", err)

    # 2. Desktop Session & Display Server
    desktop_session = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "Headless"
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    x11_display = os.environ.get("DISPLAY")

    if wayland_display:
        display_server = "Wayland"
        has_display = True
    elif x11_display:
        display_server = "X11"
        has_display = True
    else:
        display_server = "None (Headless)"
        has_display = False

    # 3. GUI Toolkit & WebKit2GTK verification
    has_gtk = False
    has_webkit2 = False
    has_pywebview = False

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401

        has_gtk = True
    except Exception:
        has_gtk = False

    try:
        import gi

        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2  # noqa: F401

        has_webkit2 = True
    except Exception:
        has_webkit2 = False

    try:
        import webview  # noqa: F401

        has_pywebview = True
    except Exception:
        has_pywebview = False

    # 4. Service Daemons (MPD, PipeWire)
    mpd_status = _check_systemd_service("mpd")
    pipewire_status = _check_systemd_service("pipewire")

    # Native desktop rendering via GTK on Linux requires both GTK3 and WebKit2GTK
    is_desktop_ready = bool(has_display and has_pywebview and has_webkit2 and has_gtk)

    return DesktopEnvironment(
        os_release=os_info,
        desktop_session=desktop_session,
        display_server=display_server,
        has_display=has_display,
        has_gtk=has_gtk,
        has_webkit2=has_webkit2,
        has_pywebview=has_pywebview,
        mpd_status=mpd_status,
        pipewire_status=pipewire_status,
        is_desktop_ready=is_desktop_ready,
        details={
            "python_version": platform.python_version(),
            "x11_display": x11_display,
            "wayland_display": wayland_display,
        },
    )


def _check_systemd_service(service_name: str) -> str:
    """Check if a systemd user service is active, inactive, or not found."""
    if not shutil.which("systemctl"):
        return "systemctl_not_available"

    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        status = res.stdout.strip()
        if res.returncode == 0 and status == "active":
            return "active"
        elif "inactive" in status or "failed" in status:
            return status
        return "inactive"
    except Exception:
        return "unknown"


def find_free_loopback_port(
    preferred_port: int = DEFAULT_BACKEND_PORT,
    host: str = DEFAULT_BACKEND_HOST,
    max_attempts: int = MAX_PORT_SEARCH_ATTEMPTS,
) -> int:
    """Detect available local loopback port, falling back dynamically if preferred port is in use.

    Args:
        preferred_port: Initial port to test (default 8000).
        host: Loopback address to bind (must be 127.0.0.1 for security).
        max_attempts: Number of incremental ports to probe.

    Returns:
        int: Guaranteed open port on the loopback interface.

    Raises:
        RuntimeError: If no free port is found within max_attempts.
    """
    safe_host = validate_loopback_host(host)

    for offset in range(max_attempts):
        candidate_port = preferred_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((safe_host, candidate_port))
                return candidate_port
            except OSError:
                continue

    raise RuntimeError(f"Unable to find a free loopback port on {safe_host} between {preferred_port} and {preferred_port + max_attempts}")


def generate_ephemeral_session_token() -> str:
    """Generate a cryptographically secure 256-bit URL-safe session token for the local webview shell."""
    return secrets.token_urlsafe(32)
