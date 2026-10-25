"""Unified Desktop Supervisor for vibeplay.

Orchestrates the entire desktop runtime:
- Detects or starts an audiophile-safe MPD daemon
- Confirms bit-perfect / PipeWire audio output routing
- Spawns the local FastAPI backend server on loopback with ephemeral session authentication
- Launches the PyWebView native GTK3/WebKit2GTK application shell
- Handles process lifecycle, SIGINT/SIGTERM, and clean teardown without orphan processes
"""

from __future__ import annotations

import atexit
import logging
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn

from vibeplay.config import Settings, get_settings
from vibeplay.desktop.constants import (
    DEFAULT_BACKEND_HOST,
    DEFAULT_BACKEND_PORT,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_MIN_HEIGHT,
    DEFAULT_WINDOW_MIN_WIDTH,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_TITLE,
)
from vibeplay.desktop.environment import (
    find_free_loopback_port,
    generate_ephemeral_session_token,
    inspect_desktop_environment,
)
from vibeplay.web import create_app

logger = logging.getLogger(__name__)

DEFAULT_MPD_DATA_DIR = Path("~/.local/share/vibeplay/mpd").expanduser()


def _is_loopback_address(host: str) -> bool:
    """Check if the provided host address is strictly a loopback address."""
    if not host or not isinstance(host, str):
        return False
    normalized = host.strip().lower()
    return normalized in ("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1") or normalized.startswith("127.")


def _sanitize_mpd_string(value: str) -> str:
    """Sanitize strings used in mpd.conf to prevent injection."""
    return value.replace("\n", "").replace("\r", "").replace("\\", "\\\\").replace('"', '\\"')


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

    Args:
        mpd_dir: Directory where MPD state files, logs, and databases are stored.
        music_dir: Root music directory (defaults to ~/Music or cwd).
        host: IP address to bind MPD to (loopback only).
        port: TCP port for MPD daemon.
        audio_outputs_block: Optional pre-configured audio outputs configuration block.

    Returns:
        str: Valid MPD configuration content.

    Raises:
        ValueError: If host is not a loopback interface.
    """
    if not _is_loopback_address(host):
        raise ValueError(f"Security guardrail: MPD daemon must bind to loopback interface only, got '{host}'")

    resolved_music_dir = (
        music_dir if music_dir is not None else (Path("~/Music").expanduser() if Path("~/Music").expanduser().exists() else Path.cwd())
    )
    mpd_dir_str = _sanitize_mpd_string(str(mpd_dir.resolve()))
    resolved_music_dir_str = _sanitize_mpd_string(str(resolved_music_dir))

    if audio_outputs_block is None:
        try:
            from vibe_dsp.alsa_reservation import generate_mpd_audio_outputs
            from vibe_dsp.hardware import scan_hardware

            audit = scan_hardware()
            primary = audit.active_dac or audit.fallback_endpoint or (audit.endpoints[0] if audit.endpoints else None)
            if primary:
                audio_outputs_block = generate_mpd_audio_outputs(primary, audit.fallback_endpoint)
            else:
                audio_outputs_block = _default_audio_outputs_fallback()
        except Exception as err:
            logger.debug("Falling back to standard audio outputs block: %s", err)
            audio_outputs_block = _default_audio_outputs_fallback()

    return f"""# ==============================================================================
# vibeplay Audiophile-Safe MPD Configuration
# ==============================================================================
music_directory     "{resolved_music_dir_str}"
playlist_directory  "{mpd_dir_str}/playlists"
db_file             "{mpd_dir_str}/tag_cache"
log_file            "{mpd_dir_str}/mpd.log"
pid_file            "{mpd_dir_str}/pid"
state_file          "{mpd_dir_str}/state"
sticker_file        "{mpd_dir_str}/sticker.sql"

bind_to_address     "{host}"
port                "{port}"
log_level           "default"
restore_paused      "yes"
auto_update         "yes"

{audio_outputs_block}
"""


def _default_audio_outputs_fallback() -> str:
    """Return fallback audio output blocks for PipeWire and ALSA."""
    return """# Audio Output 1: PipeWire Sound Server (Universal Fallback)
audio_output {
    type            "pipewire"
    name            "PipeWire Sound Server"
    enabled         "yes"
}

# Audio Output 2: Bit-Perfect ALSA Direct Default
audio_output {
    type            "alsa"
    name            "ALSA Default Hardware"
    device          "default"
    auto_resample   "no"
    auto_channels   "no"
    auto_format     "no"
    mixer_type      "none"
    enabled         "no"
}
"""


class DesktopSupervisor:
    """Supervises the unified vibeplay desktop application and service hierarchy."""

    def __init__(
        self,
        db_path: Path | None = None,
        host: str = DEFAULT_BACKEND_HOST,
        port: int = DEFAULT_BACKEND_PORT,
        settings: Settings | None = None,
        mpd_host: str | None = None,
        mpd_port: int | None = None,
        start_mpd_child: bool = True,
        auto_find_port: bool = True,
        session_token: str | None = None,
        mpd_dir: Path | None = None,
        initial_uris: list[str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db_path = db_path or self.settings.db_path.expanduser().resolve()
        self.host = host

        # Enforce loopback host security guardrail
        is_loopback = self.host in ("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1") or self.host.startswith("127.")
        if not is_loopback:
            raise ValueError(f"Security Guardrail: Desktop supervisor host must be a loopback address, got '{self.host}'")

        self.requested_port = port
        self.port = port
        self.auto_find_port = auto_find_port
        self.session_token = session_token
        self.initial_uris = list(initial_uris) if initial_uris else []

        # MPD configuration
        self.mpd_host = mpd_host or self.settings.mpd_host
        self.mpd_port = mpd_port or self.settings.mpd_port
        self.start_mpd_child = start_mpd_child
        self.mpd_dir = mpd_dir or DEFAULT_MPD_DATA_DIR
        self.mpd_process: subprocess.Popen[str] | None = None
        self.mpd_log_file: Any | None = None
        self.mpd_mode: str = "uninitialized"

        # Web server & GUI state
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.window: Any | None = None
        self.audio_config: dict[str, Any] = {}
        self.is_running = False
        self.shutdown_event = threading.Event()
        self.ready_event = threading.Event()
        self._lock = threading.RLock()

        # Register exit hook to ensure child processes are terminated
        atexit.register(self.stop)

    def confirm_audio_outputs(self) -> dict[str, Any]:
        """Inspect system audio hardware and confirm output routing capabilities.

        Returns:
            dict[str, Any]: Audio configuration and bit-perfect transport status.
        """
        info: dict[str, Any] = {
            "primary_device": "PipeWire / ALSA Default",
            "card_name": "Default Audio Device",
            "card_type": "default",
            "bit_perfect_ready": False,
            "sample_rates": ["44100", "48000", "96000"],
            "pipewire_active": False,
            "endpoints_count": 0,
        }

        # Check PipeWire daemon via wpctl
        try:
            pw_res = subprocess.run(
                ["wpctl", "status"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            info["pipewire_active"] = pw_res.returncode == 0
        except Exception:
            pass

        # Check hardware endpoints via vibe_dsp
        try:
            from vibe_dsp.hardware import scan_hardware

            audit = scan_hardware()
            info["endpoints_count"] = len(audit.endpoints)
            ep = audit.active_dac or audit.fallback_endpoint or (audit.endpoints[0] if audit.endpoints else None)
            if ep:
                info["primary_device"] = ep.hw_device
                info["card_name"] = ep.card_name
                info["card_type"] = str(ep.card_type)
                info["bit_perfect_ready"] = True
                if audit.unlocked_rates:
                    info["sample_rates"] = [str(r) for r in audit.unlocked_rates]
        except Exception as err:
            logger.debug("Hardware scan details unavailable: %s", err)

        self.audio_config = info
        logger.info(
            "Confirmed audio outputs: %s (%s, bit-perfect: %s)",
            info["card_name"],
            info["primary_device"],
            info["bit_perfect_ready"],
        )
        return info

    def _probe_mpd_socket(self, host: str, port: int, timeout: float = 0.5) -> bool:
        """Test whether an MPD daemon is reachable at the given host and port."""
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                # Read initial banner from MPD (e.g. 'OK MPD 0.23.5')
                banner = sock.recv(64).decode("utf-8", errors="replace")
                return "OK MPD" in banner
        except Exception:
            return False

    def _ensure_mpd(self) -> None:
        """Detect running MPD instance, or launch a child MPD daemon with audiophile config."""
        if not self.start_mpd_child:
            self.mpd_mode = "disabled"
            logger.info("MPD child daemon management disabled by configuration.")
            return

        # 1. Check if an external MPD instance is already running
        if self._probe_mpd_socket(self.mpd_host, self.mpd_port):
            self.mpd_mode = "attached_external"
            logger.info(
                "Detected active MPD instance at %s:%d; attaching to existing service.",
                self.mpd_host,
                self.mpd_port,
            )
            return

        # 2. Check if the mpd binary is installed
        mpd_bin = shutil.which("mpd")
        if not mpd_bin:
            self.mpd_mode = "unavailable"
            logger.warning(
                "MPD executable not found in system PATH. Playback transport will operate in standby mode. "
                "Install 'mpd' for bit-perfect hardware playback."
            )
            return

        # 3. Setup directory structure and audiophile configuration
        try:
            self.mpd_dir.mkdir(parents=True, exist_ok=True)
            (self.mpd_dir / "playlists").mkdir(parents=True, exist_ok=True)
            conf_file = self.mpd_dir / "mpd.conf"

            conf_content = generate_audiophile_mpd_config(
                mpd_dir=self.mpd_dir,
                host=self.mpd_host,
                port=self.mpd_port,
            )
            conf_file.write_text(conf_content, encoding="utf-8")

            # 4. Launch MPD as managed child process (redirecting to log file to avoid pipe deadlock)
            log_path = self.mpd_dir / "mpd.log"
            self.mpd_log_file = log_path.open("a", encoding="utf-8")

            cmd = [mpd_bin, "--no-daemon", "--stderr", str(conf_file)]
            logger.info("Spawning managed MPD child process with config %s...", conf_file)
            self.mpd_process = subprocess.Popen(
                cmd,
                stdout=self.mpd_log_file,
                stderr=self.mpd_log_file,
                text=True,
            )

            # Wait briefly and verify socket connectivity
            connected = False
            for _ in range(30):
                if self.mpd_process.poll() is not None:
                    # Process exited unexpectedly
                    last_err = ""
                    try:
                        if log_path.exists():
                            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                            last_err = " | ".join(lines[-3:]) if lines else ""
                    except Exception:
                        pass
                    logger.error("MPD child process exited prematurely: %s", last_err)
                    self.mpd_mode = "failed"
                    return
                if self._probe_mpd_socket(self.mpd_host, self.mpd_port, timeout=0.2):
                    connected = True
                    break
                time.sleep(0.1)

            if connected:
                self.mpd_mode = "managed_child"
                logger.info(
                    "Managed MPD child process started successfully (PID: %d).",
                    self.mpd_process.pid,
                )
            else:
                self.mpd_mode = "failed"
                logger.warning("MPD child process started but socket did not respond in time.")
                try:
                    self.mpd_process.terminate()
                    self.mpd_process.wait(timeout=2.0)
                except Exception:
                    self.mpd_process.kill()
                    self.mpd_process.wait(timeout=1.0)
                self.mpd_process = None
        except Exception as err:
            self.mpd_mode = "failed"
            logger.error("Failed to start managed MPD child process: %s", err)

    def _start_backend(self) -> None:
        """Initialize and run the local FastAPI backend on loopback interface."""
        if self.auto_find_port:
            self.port = find_free_loopback_port(self.requested_port, host=self.host)
        else:
            self.port = self.requested_port

        if not self.session_token:
            self.session_token = generate_ephemeral_session_token()

        masked_token = f"{self.session_token[:8]}..." if self.session_token else "none"
        logger.info(
            "Initializing FastAPI backend on %s:%d (auth token: %s)",
            self.host,
            self.port,
            masked_token,
        )

        app = create_app(
            db_path=self.db_path,
            settings=self.settings,
            api_key=self.session_token,
        )

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)

        self.server_thread = threading.Thread(
            target=self.server.run,
            name="VibeplayBackendServer",
            daemon=True,
        )
        self.server_thread.start()

        # Poll health until responsive
        health_url = f"http://{self.host}:{self.port}/docs"
        started = False
        for _ in range(50):
            try:
                with urlopen(health_url, timeout=0.2) as resp:
                    if resp.status == 200:
                        started = True
                        break
            except (URLError, OSError):
                time.sleep(0.1)

        if not started:
            if self.server is not None:
                self.server.should_exit = True
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=2.0)
            self.server = None
            self.server_thread = None
            raise RuntimeError(f"FastAPI backend failed to become ready on http://{self.host}:{self.port}")
        logger.info("FastAPI backend is ready at http://%s:%d", self.host, self.port)
        try:
            from vibeplay.desktop.mime import DEFAULT_IPC_STATE_PATH, write_ipc_state

            ipc_path = self.mpd_dir / "desktop_ipc.json" if self.mpd_dir != DEFAULT_MPD_DATA_DIR else DEFAULT_IPC_STATE_PATH
            write_ipc_state(self.host, self.port, self.session_token, state_path=ipc_path)
        except Exception as ipc_err:
            logger.debug("Could not write runtime IPC state: %s", ipc_err)

    def _launch_window(self, gui: str = "gtk") -> None:
        """Launch the PyWebView desktop application shell on the main thread."""
        try:
            import webview
        except ImportError as err:
            raise RuntimeError("pywebview is required to run the desktop GUI. Install with 'uv add pywebview'.") from err

        shell_url = f"http://{self.host}:{self.port}/?token={self.session_token}"
        masked_token = f"{self.session_token[:8]}..." if self.session_token else "none"
        logger.info(
            "Launching PyWebView desktop shell at http://%s:%d/?token=%s",
            self.host,
            self.port,
            masked_token,
        )

        self.window = webview.create_window(
            title=WINDOW_TITLE,
            url=shell_url,
            width=DEFAULT_WINDOW_WIDTH,
            height=DEFAULT_WINDOW_HEIGHT,
            min_size=(DEFAULT_WINDOW_MIN_WIDTH, DEFAULT_WINDOW_MIN_HEIGHT),
        )

        def _on_closed() -> None:
            logger.info("Desktop window close event received.")
            self.stop()

        self.window.events.closed += _on_closed

        try:
            webview.start(gui=gui)
        finally:
            self.stop()

    def start(self, headless: bool = False, gui: str = "gtk") -> None:
        """Start the supervised desktop runtime.

        Args:
            headless: If True, run backend and MPD without launching a PyWebView window.
            gui: GUI toolkit backend for pywebview ('gtk' on Linux).
        """
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self.shutdown_event.clear()
            self.ready_event.clear()

        # Register signal handlers for clean process shutdown
        try:
            signal.signal(signal.SIGINT, lambda s, f: self.stop())
            signal.signal(signal.SIGTERM, lambda s, f: self.stop())
        except (ValueError, AttributeError):
            pass

        try:
            # 1. Probe & confirm audio output configuration
            self.confirm_audio_outputs()

            # 2. Ensure MPD is active or running
            self._ensure_mpd()

            # 3. Start local backend server
            self._start_backend()

            # 3b. If launched with %U file/URI arguments, open them on the newly started backend
            if self.initial_uris:
                try:
                    from vibeplay.desktop.mime import forward_uris_to_running_instance

                    forward_uris_to_running_instance(
                        self.initial_uris,
                        host=self.host,
                        port=self.port,
                        token=self.session_token,
                    )
                except Exception as uri_err:
                    logger.warning("Failed to open initial desktop URIs: %s", uri_err)

            # 4. Check display capability
            env = inspect_desktop_environment()
            effective_headless = headless or not env.has_display

            # Signal that all supervised services are fully initialized
            self.ready_event.set()

            if effective_headless:
                if not env.has_display and not headless:
                    logger.warning("No display server detected ($DISPLAY or $WAYLAND_DISPLAY not set). Running supervisor in headless mode.")
                else:
                    logger.info("Running supervisor in headless mode.")
                try:
                    self.shutdown_event.wait()
                except KeyboardInterrupt:
                    self.stop()
            else:
                self._launch_window(gui=gui)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """Safely terminate all supervised child processes, backend servers, and windows."""
        with self._lock:
            if not self.is_running and self.shutdown_event.is_set():
                return
            self.is_running = False
            self.shutdown_event.set()
            self.ready_event.clear()

        logger.info("Initiating clean shutdown of vibeplay desktop supervisor...")

        # 1. Close PyWebView window if open
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None

        # 2. Stop FastAPI backend server
        if self.server is not None:
            self.server.should_exit = True
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=3.0)
            self.server = None
            self.server_thread = None
            logger.info("FastAPI backend server stopped.")

        # 3. Stop managed MPD child process (terminate any process spawned by this supervisor)
        if self.mpd_process is not None:
            try:
                logger.info("Terminating managed MPD process (PID: %d)...", self.mpd_process.pid)
                self.mpd_process.terminate()
                self.mpd_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning("MPD process did not exit within timeout; sending SIGKILL.")
                self.mpd_process.kill()
                self.mpd_process.wait()
            except Exception as err:
                logger.warning("Error stopping MPD process: %s", err)
            finally:
                self.mpd_process = None
                logger.info("Managed MPD process terminated.")

        # 4. Close MPD log file descriptor if opened
        if self.mpd_log_file is not None:
            try:
                self.mpd_log_file.close()
            except Exception:
                pass
            self.mpd_log_file = None

        # 5. Remove runtime IPC state file
        try:
            from vibeplay.desktop.mime import DEFAULT_IPC_STATE_PATH, clear_ipc_state

            ipc_path = self.mpd_dir / "desktop_ipc.json" if self.mpd_dir != DEFAULT_MPD_DATA_DIR else DEFAULT_IPC_STATE_PATH
            clear_ipc_state(state_path=ipc_path)
        except Exception:
            pass

        logger.info("Clean shutdown complete. All child services terminated.")

    def status(self) -> dict[str, Any]:
        """Return diagnostic health and runtime telemetry of supervised services."""
        return {
            "is_running": self.is_running,
            "is_ready": self.ready_event.is_set(),
            "host": self.host,
            "port": self.port,
            "backend_url": f"http://{self.host}:{self.port}",
            "session_token": self.session_token,
            "mpd_mode": self.mpd_mode,
            "mpd_host": self.mpd_host,
            "mpd_port": self.mpd_port,
            "mpd_pid": self.mpd_process.pid if self.mpd_process else None,
            "audio_config": self.audio_config,
            "window_open": self.window is not None,
        }


def run_desktop(
    db_path: Path | None = None,
    host: str = DEFAULT_BACKEND_HOST,
    port: int = DEFAULT_BACKEND_PORT,
    headless: bool = False,
    start_mpd_child: bool = True,
    settings: Settings | None = None,
) -> DesktopSupervisor:
    """Create, start, and return a DesktopSupervisor instance.

    Args:
        db_path: Path to SQLite database.
        host: Host address for loopback backend.
        port: Requested port for backend.
        headless: If True, do not open a GUI window.
        start_mpd_child: If True, detect or spawn managed MPD.
        settings: Application settings.

    Returns:
        DesktopSupervisor: Running supervisor instance.
    """
    supervisor = DesktopSupervisor(
        db_path=db_path,
        host=host,
        port=port,
        start_mpd_child=start_mpd_child,
        settings=settings,
    )
    supervisor.start(headless=headless)
    return supervisor
