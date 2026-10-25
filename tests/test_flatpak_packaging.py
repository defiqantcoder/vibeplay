import xml.etree.ElementTree as ET
from pathlib import Path

import yaml


def test_flatpak_manifest_specification() -> None:
    """Verify Flatpak manifest packaging/flatpak/org.vibeplay.VibePlay.yml is valid YAML."""
    repo_root = Path(__file__).resolve().parent.parent
    manifest_path = repo_root / "packaging" / "flatpak" / "org.vibeplay.VibePlay.yml"
    assert manifest_path.is_file(), "Flatpak manifest must exist"

    with manifest_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data.get("app-id") == "org.vibeplay.VibePlay"
    assert data.get("command") == "vibeplay-desktop"
    assert "finish-args" in data
    assert "--device=all" in data["finish-args"]
    assert "--socket=pulseaudio" in data["finish-args"]
    assert "--filesystem=xdg-music:ro" in data["finish-args"]

    modules = data.get("modules", [])
    module_names = []
    for m in modules:
        if isinstance(m, dict):
            module_names.append(m.get("name"))
        elif isinstance(m, str):
            module_names.append(m)
    assert "alsa-lib" in module_names
    assert "mpd" in module_names
    assert "vibeplay" in module_names


def test_flatpak_metainfo_xml() -> None:
    """Verify Flatpak AppStream metainfo XML is valid."""
    repo_root = Path(__file__).resolve().parent.parent
    metainfo_path = repo_root / "packaging" / "flatpak" / "org.vibeplay.VibePlay.metainfo.xml"
    assert metainfo_path.is_file(), "AppStream metainfo XML must exist"

    tree = ET.parse(metainfo_path)
    root = tree.getroot()

    assert root.tag == "component"
    assert root.attrib.get("type") == "desktop-application"

    id_elem = root.find("id")
    assert id_elem is not None
    assert id_elem.text == "org.vibeplay.VibePlay"

    name_elem = root.find("name")
    assert name_elem is not None
    assert name_elem.text == "VibePlay"

    screenshots_elem = root.find("screenshots")
    assert screenshots_elem is not None
    assert len(screenshots_elem.findall("screenshot")) > 0
