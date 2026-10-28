"""Lean Desktop Runner for VibePlay.

Replaces heavy supervisory daemons with a direct, fast-booting application runner:
- Starts local FastAPI backend on loopback interface with ephemeral token protection.
- Directly opens PyWebView GTK3/WebKit2GTK window or runs headless.
- Sets GTK application name, WM_CLASS, and window icon for seamless desktop integration.
- Manages clean teardown without background telemetry loops.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from vibeplay.desktop.constants import (
    DEFAULT_BACKEND_HOST,
    DEFAULT_BACKEND_PORT,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_MIN_HEIGHT,
    DEFAULT_WINDOW_MIN_WIDTH,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_TITLE,
)
from vibeplay.desktop.security import is_loopback_host, validate_loopback_host
from vibeplay.web import create_app

logger = logging.getLogger(__name__)

DEFAULT_MPD_DATA_DIR = Path("~/.local/share/vibeplay/mpd").expanduser()


def _sanitize_mpd_string(value: str) -> str:
    """Sanitize strings used in mpd.conf to prevent injection."""
    return value.replace('\n', '').replace('\r', '').replace('\\', '\\\\').replace('"', '\\"')


def generate_audiophile_mpd_config(
    mpd_dir: Path,
    music_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 6600,
    audio_outputs_block: str | None = None,
) -> str:
    """Generate an audiophile-safe MPD configuration string.

    Enforces direct hardware output with auto-resampling disabled, mixer_type none,
    and automatic fallback to PipeWire sound server.
    """
    if not is_loopback_host(host):
        raise ValueError(
            f"Security guardrail: MPD daemon must bind to loopback interface only, got '{host}'"
        )

    resolved_music_dir = (
        music_dir
        if music_dir is not None
        else (
            Path("~/Music").expanduser()
            if Path("~/Music").expanduser().exists()
            else Path.cwd()
        )
    )
    mpd_dir_str = _sanitize_mpd_string(str(mpd_dir.resolve()))
    music_dir_str = _sanitize_mpd_string(str(resolved_music_dir.resolve()))
    host_str = _sanitize_mpd_string(host)

    if audio_outputs_block:
        outputs = audio_outputs_block.strip()
    else:
        outputs = """
audio_output {
    type            "alsa"
    name            "Bit-Perfect Direct ALSA"
    device          "hw:0,0"
    mixer_type      "none"
    auto_resample   "no"
    auto_format     "no"
    auto_channels   "no"
    dop             "yes"
}

audio_output {
    type            "pipewire"
    name            "PipeWire Sound Server"
}
""".strip()

    return f"""# VibePlay Audiophile MPD Configuration
music_directory     "{music_dir_str}"
playlist_directory  "{mpd_dir_str}/playlists"
db_file             "{mpd_dir_str}/database"
log_file            "{mpd_dir_str}/log"
pid_file            "{mpd_dir_str}/pid"
state_file          "{mpd_dir_str}/state"
sticker_file        "{mpd_dir_str}/sticker.sql"

bind_to_address     "{host_str}"
port                "{port}"

auto_update         "no"
zeroconf_enabled    "no"
restore_paused      "yes"
max_output_buffer_size "16384"

{outputs}
"""


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


class DesktopRunner:
    """Lean desktop runtime manager for VibePlay."""

    def __init__(
        self,
        db_path: Path | None = None,
        host: str = DEFAULT_BACKEND_HOST,
        port: int = DEFAULT_BACKEND_PORT,
        start_mpd_child: bool = True,
        initial_uris: list[str] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.db_path = db_path
        self.start_mpd_child = start_mpd_child
        self.initial_uris = initial_uris or []

        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.mpd_proc: subprocess.Popen[Any] | None = None
        self.window: Any = None
        self.is_running: bool = False
        self.ready_event = threading.Event()
        self._shutdown_lock = threading.Lock()

        validate_loopback_host(self.host)

    def _start_mpd_if_needed(self) -> None:
        """Verify MPD is reachable or launch managed instance."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        res = sock.connect_ex(("127.0.0.1", 6600))
        sock.close()
        if res == 0:
            logger.info("Found existing MPD daemon at 127.0.0.1:6600")
            return

        if not self.start_mpd_child:
            return

        mpd_bin = shutil.which("mpd")
        if not mpd_bin:
            logger.warning("MPD binary not found in PATH; operating in fallback mode.")
            return

        mpd_dir = DEFAULT_MPD_DATA_DIR
        mpd_dir.mkdir(parents=True, exist_ok=True)
        (mpd_dir / "playlists").mkdir(parents=True, exist_ok=True)
        conf_file = mpd_dir / "mpd.conf"
        conf_file.write_text(generate_audiophile_mpd_config(mpd_dir=mpd_dir, host="127.0.0.1", port=6600))

        try:
            self.mpd_proc = subprocess.Popen(
                [mpd_bin, "--no-daemon", "--stderr", str(conf_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.3)
            logger.info("Spawned child MPD process PID %d", self.mpd_proc.pid)
        except Exception as e:
            logger.warning("Could not launch child MPD daemon: %s", e)

    def _start_backend_server(self) -> None:
        """Launch uvicorn server in a dedicated background thread."""
        app = create_app(db_path=self.db_path)
        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="warning",
            loop="asyncio",
        )
        self.server = uvicorn.Server(config)

        def _serve() -> None:
            self.ready_event.set()
            try:
                self.server.run()
            except Exception as exc:
                logger.error("Backend uvicorn server exited with error: %s", exc)

        self.server_thread = threading.Thread(target=_serve, name="vibeplay-backend", daemon=True)
        self.server_thread.start()

        # Wait until server port is listening
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                with urlopen(f"http://{self.host}:{self.port}/api/health", timeout=0.2) as resp:
                    if resp.status == 200:
                        break
            except (URLError, OSError):
                time.sleep(0.05)

    def start(self, headless: bool = False) -> None:
        """Start backend services and PyWebView GUI window."""
        self.is_running = True
        atexit.register(self.stop)

        self._start_mpd_if_needed()
        self._start_backend_server()

        if headless:
            logger.info("Running vibeplay desktop in headless mode on http://%s:%d", self.host, self.port)
            try:
                while self.is_running:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                self.stop()
            return

        # Setup GTK application name, WM_CLASS, and window icon
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

        try:
            import webview

            url = f"http://{self.host}:{self.port}/"
            self.window = webview.create_window(
                title=WINDOW_TITLE,
                url=url,
                width=DEFAULT_WINDOW_WIDTH,
                height=DEFAULT_WINDOW_HEIGHT,
                min_size=(DEFAULT_WINDOW_MIN_WIDTH, DEFAULT_WINDOW_MIN_HEIGHT),
                text_select=True,
            )
            webview.start()
        except Exception as err:
            logger.error("PyWebView GUI failure: %s", err)
        finally:
            self.stop()

    def stop(self) -> None:
        """Teardown backend server and child processes cleanly."""
        with self._shutdown_lock:
            if not self.is_running:
                return
            self.is_running = False

            if self.server:
                self.server.should_exit = True

            if self.mpd_proc:
                try:
                    self.mpd_proc.terminate()
                    self.mpd_proc.wait(timeout=0.5)
                except Exception:
                    try:
                        self.mpd_proc.kill()
                    except Exception:
                        pass
                self.mpd_proc = None

            logger.info("VibePlay desktop runner stopped cleanly.")


def run_desktop(
    host: str = DEFAULT_BACKEND_HOST,
    port: int = DEFAULT_BACKEND_PORT,
    db_path: Path | None = None,
    headless: bool = False,
    start_mpd: bool = True,
) -> DesktopRunner:
    """Convenience launcher for VibePlay desktop player."""
    runner = DesktopRunner(
        db_path=db_path,
        host=host,
        port=port,
        start_mpd_child=start_mpd,
    )
    runner.start(headless=headless)
    return runner
