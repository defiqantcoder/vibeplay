import os
import subprocess
from pathlib import Path
from unittest import mock

from vibeplay.desktop.notifications import TrackNotificationDispatcher


def test_vibeplay_desktop_file_contents():
    desktop_file = Path("packaging/vibeplay.desktop")
    assert desktop_file.exists()
    content = desktop_file.read_text()

    assert "Type=Application" in content
    assert "Name=VibePlay" in content
    assert "Exec=vibeplay-desktop %U" in content
    assert "Categories=AudioVideo;Audio;Player;GTK;" in content
    assert "MimeType=audio/flac;audio/x-flac;audio/mpeg;audio/ogg;audio/wav;audio/x-wav;audio/aac;audio/mp4;" in content
    assert "SingleMainWindow=true" in content
    assert "[Desktop Action HeadlessScan]" in content
    assert "Exec=vibeplay scan" in content
    assert "[Desktop Action PlayPause]" in content


def test_vibeplay_service_file_contents():
    service_file = Path("packaging/vibeplay.service")
    assert service_file.exists()
    content = service_file.read_text()

    assert "[Unit]" in content
    assert "Description=VibePlay Headless Audio Indexing & Loopback API Service" in content
    assert "After=network.target sound.target mpd.service" in content
    assert "[Service]" in content
    # Ensure it binds strictly to loopback 127.0.0.1
    assert "ExecStart=/usr/bin/env vibeplay serve --host 127.0.0.1 --port 8000" in content
    assert "NoNewPrivileges=true" in content
    assert "PrivateTmp=true" in content
    assert "[Install]" in content
    assert "WantedBy=default.target" in content


@mock.patch("vibeplay.desktop.notifications.shutil.which")
@mock.patch("vibeplay.desktop.notifications.subprocess.run")
def test_track_notification_dispatcher(mock_run, mock_which):
    mock_which.return_value = "/usr/bin/notify-send"

    dispatcher = TrackNotificationDispatcher()

    # First transition
    dispatcher.notify_transition("My Track", "My Artist", "My Album", "96kHz/24-bit FLAC", track_id="123", track_path="/path/to/123.flac")

    mock_run.assert_called_once_with(
        ["/usr/bin/notify-send", "--app-name=VibePlay", "--icon=vibeplay", "My Track", "My Artist — My Album [96kHz/24-bit FLAC]"],
        shell=False,
        timeout=5,
        check=True,
    )

    mock_run.reset_mock()

    # Duplicate transition
    dispatcher.notify_transition("My Track", "My Artist", "My Album", "96kHz/24-bit FLAC", track_id="123", track_path="/path/to/123.flac")
    mock_run.assert_not_called()

    # Fallback to path if track_id is different but path is same (hypothetical, but let's just test changing id)
    dispatcher.notify_transition("My Track", "My Artist", "My Album", "96kHz/24-bit FLAC", track_id="124", track_path="/path/to/123.flac")
    mock_run.assert_not_called()  # because path is same

    # New transition
    dispatcher.notify_transition("New Track", "New Artist", "New Album", "MP3", track_id="456", track_path="/path/to/456.mp3")
    mock_run.assert_called_once()

    # Test notify_track_change wrapper
    mock_run.reset_mock()
    dispatcher.notify_track_change(
        track_id="789",
        title="Hi-Res Track",
        artist="Audiophile Artist",
        album="Studio Sessions",
        sample_rate="192.0kHz",
        bit_depth="24-bit",
    )
    mock_run.assert_called_once_with(
        ["/usr/bin/notify-send", "--app-name=VibePlay", "--icon=vibeplay", "Hi-Res Track", "Audiophile Artist — Studio Sessions [192.0kHz / 24-bit]"],
        shell=False,
        timeout=5,
        check=True,
    )


@mock.patch("vibeplay.desktop.notifications.shutil.which")
@mock.patch("vibeplay.desktop.notifications.subprocess.run")
def test_track_notification_dispatcher_fallback(mock_run, mock_which):
    # Test when notify-send is missing
    mock_which.return_value = None
    dispatcher = TrackNotificationDispatcher()
    dispatcher.notify_transition("Track", "Artist", "Album", "FLAC", track_id="1")
    mock_run.assert_not_called()


@mock.patch("vibeplay.desktop.notifications.shutil.which")
@mock.patch("vibeplay.desktop.notifications.subprocess.run")
def test_track_notification_dispatcher_error(mock_run, mock_which):
    # Test graceful fallback when notify-send errors
    mock_which.return_value = "/usr/bin/notify-send"
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
    dispatcher = TrackNotificationDispatcher()
    # Should not raise exception
    dispatcher.notify_transition("Track", "Artist", "Album", "FLAC", track_id="1")
    mock_run.assert_called_once()


def test_install_script_dry_run(tmp_path):
    script_path = Path("scripts/install-desktop.sh").resolve()
    assert script_path.exists()

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)

    # Run script with --dry-run
    result = subprocess.run(
        [str(script_path), "--prefix", str(tmp_path), "--dry-run", "--enable-systemd"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "[Dry Run] Would install to prefix:" in result.stdout

    # Run script to actual temp dir without dist/vibeplay
    result2 = subprocess.run(
        [str(script_path), "--prefix", str(tmp_path), "--enable-systemd"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result2.returncode == 0
    assert "Installation complete!" in result2.stdout

    assert (tmp_path / "bin" / "vibeplay-desktop").exists()
    assert (tmp_path / "bin" / "vibeplay").exists()
    assert (tmp_path / "share" / "icons" / "hicolor" / "scalable" / "apps" / "vibeplay.svg").exists()
    assert (tmp_path / "share" / "applications" / "vibeplay.desktop").exists()
    assert (tmp_path / ".config" / "systemd" / "user" / "vibeplay.service").exists()
