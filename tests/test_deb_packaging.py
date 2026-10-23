"""Tests for Debian (.deb) and Flatpak packaging specifications."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml


def test_debian_control_file_specification() -> None:
    """Verify packaging/debian/control adheres to Debian package policy."""
    repo_root = Path(__file__).resolve().parent.parent
    control_path = repo_root / "packaging" / "debian" / "control"
    assert control_path.is_file(), "packaging/debian/control must exist"

    content = control_path.read_text(encoding="utf-8")
    fields = {}
    for line in content.splitlines():
        if ":" in line and not line.startswith(" "):
            key, val = line.split(":", 1)
            fields[key.strip()] = val.strip()

    assert fields.get("Package") == "vibeplay"
    assert fields.get("Architecture") == "amd64"
    assert "libwebkit2gtk-4.1-0" in fields.get("Depends", "")
    assert "mpd" in fields.get("Depends", "")
    assert "libasound2" in fields.get("Depends", "")


def test_debian_maintainer_scripts() -> None:
    """Verify postinst and postrm scripts exist and handle desktop/icon caches."""
    repo_root = Path(__file__).resolve().parent.parent
    postinst = repo_root / "packaging" / "debian" / "postinst"
    postrm = repo_root / "packaging" / "debian" / "postrm"

    assert postinst.is_file()
    assert postrm.is_file()

    for script in (postinst, postrm):
        text = script.read_text(encoding="utf-8")
        assert "#!/bin/sh" in text
        assert "update-desktop-database" in text
        assert "gtk-update-icon-cache" in text


def test_build_deb_script_generates_valid_archive(tmp_path: Path) -> None:
    """Verify scripts/build-deb.sh builds a valid .deb archive verifiable by dpkg-deb."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "build-deb.sh"
    assert script_path.is_file()
    assert os.access(script_path, os.X_OK), "scripts/build-deb.sh must be executable"

    # Run build-deb.sh in test mode with --skip-pyinstaller
    res = subprocess.run(
        [str(script_path), "--skip-pyinstaller"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"build-deb.sh failed: {res.stderr}"

    deb_path = repo_root / "dist" / "vibeplay_0.1.0_amd64.deb"
    assert deb_path.is_file(), "Output debian package must exist in dist/"

    # Inspect package via dpkg-deb if installed
    dpkg_info = subprocess.run(
        ["dpkg-deb", "-I", str(deb_path)],
        capture_output=True,
        text=True,
    )
    assert dpkg_info.returncode == 0
    assert "Package: vibeplay" in dpkg_info.stdout

    dpkg_contents = subprocess.run(
        ["dpkg-deb", "-c", str(deb_path)],
        capture_output=True,
        text=True,
    )
    assert dpkg_contents.returncode == 0
    contents = dpkg_contents.stdout
    assert "./usr/bin/vibeplay-desktop" in contents
    assert "./usr/share/applications/vibeplay.desktop" in contents
    assert "./usr/share/icons/hicolor/scalable/apps/vibeplay.svg" in contents
    assert "./usr/lib/systemd/user/vibeplay.service" in contents


def test_flatpak_manifest_specification() -> None:
    """Verify Flatpak manifest packaging/flatpak/com.vibeplay.VibePlay.yaml is valid YAML."""
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "packaging" / "flatpak" / "com.vibeplay.VibePlay.yaml"
    assert manifest_path.is_file(), "Flatpak manifest must exist"

    with manifest_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data.get("app-id") == "com.vibeplay.VibePlay"
    assert data.get("command") == "vibeplay-desktop"
    assert "finish-args" in data
    assert "--device=all" in data["finish-args"]
    assert "--socket=pulseaudio" in data["finish-args"]
