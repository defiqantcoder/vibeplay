"""Tests for Phase 1 Unified Desktop Supervisor and runtime orchestration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import urlopen

import pytest

from vibeplay.desktop.constants import DEFAULT_BACKEND_HOST, DEFAULT_BACKEND_PORT
from vibeplay.desktop.supervisor import (
    DesktopSupervisor,
    generate_audiophile_mpd_config,
    run_desktop,
)


def test_generate_audiophile_mpd_config(tmp_path: Path) -> None:
    """Verify audiophile MPD configuration generation contains bit-perfect directives."""
    mpd_dir = tmp_path / "mpd"
    music_dir = tmp_path / "music"
    music_dir.mkdir()

    conf = generate_audiophile_mpd_config(
        mpd_dir=mpd_dir,
        music_dir=music_dir,
        host="127.0.0.1",
        port=6600,
    )

    assert f'music_directory     "{music_dir.resolve()}"' in conf
    assert f'playlist_directory  "{mpd_dir.resolve()}/playlists"' in conf
    assert f'db_file             "{mpd_dir.resolve()}/tag_cache"' in conf
    assert 'bind_to_address     "127.0.0.1"' in conf
    assert 'port                "6600"' in conf
    assert 'auto_resample   "no"' in conf
    assert 'mixer_type      "none"' in conf


def test_confirm_audio_outputs(tmp_path: Path) -> None:
    """Verify audio output configuration inspection returns expected structure."""
    db_file = tmp_path / "vibeplay.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)
    outputs = supervisor.confirm_audio_outputs()

    assert "primary_device" in outputs
    assert "card_name" in outputs
    assert "bit_perfect_ready" in outputs
    assert "sample_rates" in outputs
    assert "pipewire_active" in outputs
    assert isinstance(outputs["sample_rates"], list)


def test_supervisor_initialization(tmp_path: Path) -> None:
    """Verify DesktopSupervisor initializes with safe loopback defaults and ephemeral tokens."""
    db_file = tmp_path / "test.db"
    db_file.touch()

    supervisor = DesktopSupervisor(
        db_path=db_file,
        host=DEFAULT_BACKEND_HOST,
        port=8042,
        start_mpd_child=False,
    )

    assert supervisor.host == "127.0.0.1"
    assert supervisor.requested_port == 8042
    assert supervisor.is_running is False
    assert supervisor.mpd_mode == "uninitialized"


def test_mpd_attached_when_already_running(tmp_path: Path) -> None:
    """Verify supervisor attaches to existing MPD instance when probe succeeds."""
    db_file = tmp_path / "test.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=True)

    with patch.object(supervisor, "_probe_mpd_socket", return_value=True):
        supervisor._ensure_mpd()
        assert supervisor.mpd_mode == "attached_external"
        assert supervisor.mpd_process is None


def test_mpd_unavailable_when_binary_missing(tmp_path: Path) -> None:
    """Verify supervisor gracefully enters standby when MPD binary is not installed."""
    db_file = tmp_path / "test.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=True)

    with patch.object(supervisor, "_probe_mpd_socket", return_value=False):
        with patch("shutil.which", return_value=None):
            supervisor._ensure_mpd()
            assert supervisor.mpd_mode == "unavailable"
            assert supervisor.mpd_process is None


def test_mpd_disabled_by_configuration(tmp_path: Path) -> None:
    """Verify supervisor marks MPD as disabled when start_mpd_child is False."""
    db_file = tmp_path / "test.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)
    supervisor._ensure_mpd()
    assert supervisor.mpd_mode == "disabled"
    assert supervisor.mpd_process is None


def test_mpd_spawn_managed_child(tmp_path: Path) -> None:
    """Verify supervisor spawns and monitors child MPD process when needed."""
    db_file = tmp_path / "test.db"
    db_file.touch()
    mpd_dir = tmp_path / "mpd_test"

    supervisor = DesktopSupervisor(
        db_path=db_file,
        start_mpd_child=True,
        mpd_dir=mpd_dir,
    )

    mock_process = MagicMock(spec=subprocess.Popen)
    mock_process.poll.return_value = None
    mock_process.pid = 9999

    # First probe fails (not running), then after spawn probe succeeds
    probe_results = [False, True]

    def mock_probe(*args, **kwargs):
        return probe_results.pop(0) if probe_results else True

    with patch.object(supervisor, "_probe_mpd_socket", side_effect=mock_probe):
        with patch("shutil.which", return_value="/usr/bin/mpd"):
            with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
                supervisor._ensure_mpd()
                assert supervisor.mpd_mode == "managed_child"
                assert supervisor.mpd_process is mock_process
                mock_popen.assert_called_once()

    # Now verify clean stop terminates the process
    supervisor.is_running = True
    supervisor.stop()
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_called_once()
    assert supervisor.mpd_process is None


def test_supervisor_backend_and_headless_lifecycle(tmp_path: Path) -> None:
    """Verify complete headless startup, backend reachability, status telemetry, and stop."""
    from vibeplay.db import init_db

    db_file = tmp_path / "lifecycle.db"
    init_db(db_file)

    supervisor = DesktopSupervisor(
        db_path=db_file,
        host="127.0.0.1",
        port=DEFAULT_BACKEND_PORT,
        start_mpd_child=False,
    )

    # Start supervisor in headless mode in a background thread
    import threading

    start_thread = threading.Thread(
        target=lambda: supervisor.start(headless=True),
        daemon=True,
    )
    start_thread.start()

    # Wait for supervisor to finish startup and signal readiness
    assert supervisor.ready_event.wait(timeout=10.0), "Supervisor failed to become ready within timeout"

    assert supervisor.is_running is True
    assert supervisor.port >= DEFAULT_BACKEND_PORT
    assert supervisor.session_token is not None

    # Verify backend URL responds
    backend_url = f"http://127.0.0.1:{supervisor.port}/docs"
    with urlopen(backend_url, timeout=2.0) as resp:
        assert resp.status == 200

    # Verify status report
    st = supervisor.status()
    assert st["is_running"] is True
    assert st["is_ready"] is True
    assert st["port"] == supervisor.port
    assert st["mpd_mode"] == "disabled"
    assert "audio_config" in st

    # Stop supervisor and verify clean shutdown
    supervisor.stop()
    start_thread.join(timeout=3.0)

    assert supervisor.is_running is False
    assert supervisor.server is None
    assert supervisor.server_thread is None


def test_supervisor_reentrant_stop(tmp_path: Path) -> None:
    """Verify stop() can be called multiple times without error."""
    db_file = tmp_path / "stop_test.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)
    supervisor.stop()
    supervisor.stop()
    assert supervisor.is_running is False


def test_supervisor_signal_handling(tmp_path: Path) -> None:
    """Verify signal registration and handling triggers stop()."""
    db_file = tmp_path / "sig_test.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)
    supervisor.is_running = True

    # Test invoking stop directly as signal handler does
    supervisor.stop()
    assert supervisor.is_running is False
    assert supervisor.shutdown_event.is_set()


def test_cli_entrypoint_help_and_version() -> None:
    """Verify desktop __main__ argument parser."""
    from vibeplay.desktop.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_cli_app_desktop_command() -> None:
    """Verify typer vibeplay desktop command prints help."""
    from typer.testing import CliRunner

    from vibeplay.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["desktop", "--help"])
    assert result.exit_code == 0
    assert "Launch the unified vibeplay desktop application" in result.output


def test_run_desktop_function(tmp_path: Path) -> None:
    """Verify run_desktop helper instantiates and starts supervisor."""
    db_file = tmp_path / "run_func.db"
    db_file.touch()

    with patch.object(DesktopSupervisor, "start") as mock_start:
        sup = run_desktop(db_path=db_file, headless=True, start_mpd_child=False)
        assert isinstance(sup, DesktopSupervisor)
        mock_start.assert_called_once_with(headless=True)


def test_supervisor_rejects_non_loopback(tmp_path: Path) -> None:
    """Verify DesktopSupervisor raises ValueError if host is not a loopback address."""
    db_file = tmp_path / "reject.db"
    db_file.touch()

    with pytest.raises(ValueError, match="Security Guardrail"):
        DesktopSupervisor(db_path=db_file, host="192.168.1.100")


def test_mpd_child_early_crash(tmp_path: Path) -> None:
    """Verify supervisor detects early crash of child MPD process."""
    db_file = tmp_path / "crash.db"
    db_file.touch()
    mpd_dir = tmp_path / "mpd_crash"

    supervisor = DesktopSupervisor(
        db_path=db_file,
        start_mpd_child=True,
        mpd_dir=mpd_dir,
    )

    mock_process = MagicMock(spec=subprocess.Popen)
    mock_process.poll.return_value = 1  # Crashed immediately
    mock_process.pid = 8888

    with patch.object(supervisor, "_probe_mpd_socket", return_value=False):
        with patch("shutil.which", return_value="/usr/bin/mpd"):
            with patch("subprocess.Popen", return_value=mock_process):
                supervisor._ensure_mpd()
                assert supervisor.mpd_mode == "failed"


def test_launch_window_mock(tmp_path: Path) -> None:
    """Verify _launch_window attaches event handler and starts webview with GTK."""
    db_file = tmp_path / "win.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)
    supervisor.port = 8000
    supervisor.session_token = "mock-secret-token"

    mock_window = MagicMock()
    mock_window.events.closed = MagicMock()

    with patch("webview.create_window", return_value=mock_window) as mock_create:
        with patch("webview.start") as mock_start:
            supervisor._launch_window(gui="gtk")
            mock_create.assert_called_once()
            args, kwargs = mock_create.call_args
            assert "token=mock-secret-token" in kwargs["url"]
            assert kwargs["title"] == "vibeplay — Audiophile Precision Console"
            assert kwargs["width"] == 1380
            assert kwargs["height"] == 860
            mock_start.assert_called_once_with(gui="gtk")


def test_generate_audiophile_mpd_config_rejects_non_loopback(tmp_path: Path) -> None:
    """Verify generate_audiophile_mpd_config raises ValueError on non-loopback host."""
    mpd_dir = tmp_path / "mpd_sec"
    with pytest.raises(ValueError, match="Security guardrail"):
        generate_audiophile_mpd_config(mpd_dir=mpd_dir, host="0.0.0.0")

    with pytest.raises(ValueError, match="Security guardrail"):
        generate_audiophile_mpd_config(mpd_dir=mpd_dir, host="192.168.1.50")


def test_mpd_socket_timeout_cleans_up_process(tmp_path: Path) -> None:
    """Verify supervisor terminates and clears spawned MPD process if socket connection times out."""
    db_file = tmp_path / "timeout.db"
    db_file.touch()
    mpd_dir = tmp_path / "mpd_timeout"

    supervisor = DesktopSupervisor(
        db_path=db_file,
        start_mpd_child=True,
        mpd_dir=mpd_dir,
    )

    mock_process = MagicMock(spec=subprocess.Popen)
    mock_process.poll.return_value = None
    mock_process.pid = 7777

    with patch.object(supervisor, "_probe_mpd_socket", return_value=False):
        with patch("shutil.which", return_value="/usr/bin/mpd"):
            with patch("subprocess.Popen", return_value=mock_process):
                supervisor._ensure_mpd()
                assert supervisor.mpd_mode == "failed"
                mock_process.terminate.assert_called_once()
                assert supervisor.mpd_process is None


def test_backend_startup_timeout_cleanup(tmp_path: Path) -> None:
    """Verify _start_backend cleans up uvicorn server thread on startup timeout."""
    db_file = tmp_path / "backend_fail.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)

    with patch("vibeplay.desktop.supervisor.urlopen", side_effect=OSError("Connection refused")):
        with pytest.raises(RuntimeError, match="FastAPI backend failed to become ready"):
            supervisor._start_backend()

    assert supervisor.server is None
    assert supervisor.server_thread is None


def test_window_close_event_triggers_stop(tmp_path: Path) -> None:
    """Verify window closed event handler invokes supervisor.stop()."""
    db_file = tmp_path / "win_close.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)
    supervisor.is_running = True

    mock_window = MagicMock()
    captured_callbacks = []

    def mock_iadd(*args, **kwargs):
        if args:
            captured_callbacks.append(args[-1])
        return mock_window.events.closed

    mock_window.events.closed.__iadd__.side_effect = mock_iadd

    with patch("webview.create_window", return_value=mock_window):
        with patch("webview.start", side_effect=lambda **kwargs: captured_callbacks[0]()):
            supervisor._launch_window(gui="gtk")

    assert supervisor.is_running is False
    assert supervisor.shutdown_event.is_set()


def test_start_failure_cleans_up(tmp_path: Path) -> None:
    """Verify start() invokes stop() if an exception occurs during startup."""
    db_file = tmp_path / "start_err.db"
    db_file.touch()

    supervisor = DesktopSupervisor(db_path=db_file, start_mpd_child=False)

    with patch.object(supervisor, "confirm_audio_outputs", side_effect=RuntimeError("Audio hardware fault")):
        with patch.object(supervisor, "stop") as mock_stop:
            with pytest.raises(RuntimeError, match="Audio hardware fault"):
                supervisor.start(headless=True)
            mock_stop.assert_called_once()
