"""Unit and integration tests for Phase 2: Desktop App Chrome, Menubar, Settings Dialog, and Theme Engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db
from vibeplay.ui.theme import THEME_PRESETS, generate_all_themes_css
from vibeplay.web import create_app


@pytest.fixture
def desktop_client(tmp_path: Path) -> TestClient:
    """Fixture providing isolated FastAPI TestClient with initialized SQLite database."""
    db_file = tmp_path / "desktop_test.db"
    init_db(db_file)
    with get_connection(db_file) as conn:
        conn.execute(
            """
            INSERT INTO tracks (id, path, mtime, size, hash, duration, tags)
            VALUES (1, '/music/audiophile.flac', 1000.0, 1024, 'dummy_hash', 240.0, '{"title": "Studio Master", "artist": "Audiophile Trio", "album": "Precision Album", "genre": "Lossless Jazz"}')
            """
        )
        conn.execute(
            """
            INSERT INTO features (track_id, analyzer_version, bpm, key, scale, danceability, energy, mood_scores)
            VALUES (1, '1.0.0', 120.0, 'B', 'minor', 0.65, 0.78, '{"electronic": 0.88, "relaxed": 0.74, "acoustic": 0.65, "party": 0.42, "happy": 0.22, "aggressive": 0.12}')
            """
        )
    settings = Settings(db_path=db_file)
    app = create_app(db_path=db_file, settings=settings)
    return TestClient(app)


class TestThemeEngine:
    """Tests for CSS theme generation and custom properties."""

    def test_themes_definition_contains_all_six_presets(self) -> None:
        expected_themes = {
            "god-of-ink",
            "wine",
            "obsidian",
            "swimming-with-the-whales",
            "mint-city",
            "slate-audiophile",
            "beyond-the-boundary",
            "the-unknown",
            "castle-in-the-sky",
        }
        preset_ids = {p.id for p in THEME_PRESETS}
        assert preset_ids == expected_themes
        for preset in THEME_PRESETS:
            assert preset.name
            assert preset.description
            assert "--bg-base" in preset.variables
            assert "--bg-surface" in preset.variables
            assert "--text" in preset.variables
            assert "--primary" in preset.variables
            assert "--accent" in preset.variables

    def test_generate_all_themes_css_outputs_css_variables(self) -> None:
        css = generate_all_themes_css()
        assert ":root" in css
        assert "--bg-canvas:" in css

        for preset in THEME_PRESETS:
            selector = f"data-theme='{preset.id}'"
            assert selector in css


class TestDesktopApiEndpoints:
    """Tests for backend desktop chrome and control endpoints."""

    def test_get_menu_hierarchy_returns_seven_sections(self, desktop_client: TestClient) -> None:
        resp = desktop_client.get("/api/menu")
        assert resp.status_code == 200
        menus = resp.json()
        assert isinstance(menus, list)
        assert len(menus) == 7
        section_ids = [m["id"] for m in menus]
        assert section_ids == ["file", "edit", "library", "playback", "dsp", "view", "help"]

        # Check File menu items
        file_menu = next(m for m in menus if m["id"] == "file")
        shortcuts = [item["shortcut"] for item in file_menu["items"] if item.get("shortcut")]
        assert "Ctrl+O" in shortcuts
        assert "Ctrl+R" in shortcuts
        assert "Ctrl+," in shortcuts
        assert "Ctrl+Q" in shortcuts

    def test_get_themes_presets(self, desktop_client: TestClient) -> None:
        resp = desktop_client.get("/api/themes")
        assert resp.status_code == 200
        themes = resp.json()
        assert isinstance(themes, list)
        assert len(themes) == 9
        theme_ids = [t["id"] for t in themes]
        assert "god-of-ink" in theme_ids
        assert "obsidian" in theme_ids
        assert "slate-audiophile" in theme_ids
        assert "beyond-the-boundary" in theme_ids
        assert "the-unknown" in theme_ids
        assert "castle-in-the-sky" in theme_ids

    def test_player_clear_endpoint(self, desktop_client: TestClient) -> None:
        resp = desktop_client.post("/api/player/clear")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "cleared"

    def test_dsp_telemetry_endpoint(self, desktop_client: TestClient) -> None:
        resp = desktop_client.get("/api/dsp/telemetry")
        assert resp.status_code == 200
        data = resp.json()
        assert "xruns" in data
        assert "jitter_ppm" in data
        assert "buffer_health" in data
        assert "active_profile" in data

    def test_dsp_spatial_toggle_endpoint(self, desktop_client: TestClient) -> None:
        with (
            patch("vibe_dsp.spatial.get_spatial_virtualization_status", return_value="stereo_direct"),
            patch("vibe_dsp.spatial.set_spatial_virtualization_mode", return_value={"mode": "spatial_binaural", "status": "active"}),
        ):
            resp = desktop_client.post("/api/dsp/spatial/toggle")
            assert resp.status_code == 200
            data = resp.json()
            assert data["mode"] == "spatial_binaural"

    def test_app_quit_endpoint(self, desktop_client: TestClient) -> None:
        with patch("threading.Timer") as mock_timer:
            mock_timer_inst = MagicMock()
            mock_timer.return_value = mock_timer_inst
            resp = desktop_client.post("/api/app/quit")
            assert resp.status_code == 200
            assert resp.json() == {"status": "shutting_down"}
            mock_timer.assert_called_once()
            mock_timer_inst.start.assert_called_once()


class TestDesktopShellRendering:
    """Tests for HTML rendering of the desktop shell, titlebar, menubar, and dialogs."""

    def test_index_page_contains_desktop_chrome_and_controls(self, desktop_client: TestClient) -> None:
        resp = desktop_client.get("/")
        assert resp.status_code == 200
        html = resp.text

        # 1. Simulated Window Titlebar
        assert 'class="desktop-titlebar"' in html
        assert 'class="window-controls"' in html
        assert "dot-close" in html
        assert "dot-minimize" in html
        assert "dot-maximize" in html
        assert "VIBEPLAY" in html
        assert "Active Desktop Session:" in html

        # Status indicators
        assert "0 xruns" in html
        assert "Bit-Perfect Sync" in html
        assert "Exclusive Mode" in html

        # 2. Desktop Menubar
        assert 'class="desktop-menubar"' in html
        assert 'role="menubar"' in html
        for section in ["File", "Edit", "Library", "Playback", "DSP", "View", "Help"]:
            assert f"<span>{section}</span>" in html

        # Submenus and shortcuts
        assert "Export Formats" in html
        assert "UTF-8 M3U8" in html
        assert "Ctrl+R" in html
        assert "Ctrl+O" in html
        assert "Ctrl+," in html
        assert "Ctrl+Q" in html
        assert "Space / F10" in html
        assert "F9" in html
        assert "F11" in html
        assert "F12" in html

        # 3. Settings Dialog & 4 Tabs
        assert 'id="settings-dialog"' in html
        assert 'class="settings-tabs-bar"' in html
        assert "ALSA Transport" in html
        assert "DSP &amp; Profiles" in html or "DSP & Profiles" in html
        assert "Feature Engine" in html
        assert "Theme Engine" in html

        # 4. Color Themes Palette Presets
        assert "God of Ink" in html
        assert "Wine" in html
        assert "Obsidian" in html
        assert "Swimming with the Whales" in html
        assert "Mint City" in html
        assert "Slate Audiophile" in html

        # 5. Client Scripts
        assert "initThemeEngine" in html
        assert "applyTheme" in html
        assert "switchSettingsTab" in html
        assert "toggleSettingsDialog" in html

        # 6. Stitch HUD Micro-Visualizers (Screen 3)
        assert "telemetry-oscilloscope" in html
        assert "segmented-meter-well" in html
        assert "harmonic-chips-row" in html
        assert "histogram-bars-row" in html
        assert "table-footnote" in html
        assert "I²S SYNC" in html
        assert "DR14+ MASTER" in html
        assert "DMA Ring Buffer: 128 frames" in html

        # 7. Stitch 3-Column Studio Workspace Layout (Screen 5b4e60ea)
        assert 'class="workspace-layout"' in html
        assert 'class="workspace-sidebar"' in html
        assert 'class="workspace-center"' in html
        assert 'class="workspace-inspector"' in html
        assert 'id="workspace-inspector-drawer"' in html
        assert 'id="workspace-inspector-content"' in html
        assert "Hardware Inspect" in html
        assert "Acoustic Vibe Matrix" in html
        assert "Harmonic Zones" in html
        assert "Audio Hardware Sync" in html

        # 8. Interactive Mood-First Chips and Harmonic Matrix
        assert 'class="mood-chip active"' in html
        assert 'data-mood="chill"' in html
        assert 'data-mood="electronic"' in html
        assert 'class="harmonic-zone-btn"' in html
        assert 'data-camelot="8A"' in html
        assert 'data-camelot="10A"' in html
        assert "filterByHarmonicKey" in html
        assert "selectMoodChip" in html
        assert "syncBpmSlider" in html

        # 9. Extended Themes in Settings Dialog
        assert "Beyond the Boundary" in html
        assert "The Unknown" in html
        assert "Castle In The Sky" in html

    def test_track_inspector_endpoint(self, desktop_client: TestClient) -> None:
        """Verify GET /api/track/{track_id}?view=inspector returns the docked telemetry drawer fragment."""
        resp = desktop_client.get("/api/track/1?view=inspector")
        assert resp.status_code == 200
        html = resp.text
        assert "inspector-wrapper" in html
        assert "Audio Signal Telemetry" in html
        assert "Acoustic Identifiers" in html
        assert "Neural Mood Inference" in html
        assert "CODEC" in html
        assert "SAMPLE RATE" in html
        assert "BIT DEPTH" in html
        assert "Harmonic Zone:" in html
        assert "Transferred via USB 3.2 Gen2" in html
