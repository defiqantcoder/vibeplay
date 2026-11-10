"""Unit and integration tests for UI BUG FIX DIRECTIVE: SCREEN ISOLATION & METADATA BINDING.

Verifies:
1. Screen separation: Lo-Fi Lounge, Master Crate, Record Crate Shelves, and Vibe Generator
   are isolated in separate view panels, active/hidden by default, and mock lounge listeners stripped.
2. Dynamic audio metadata & bit-depth bindings in library table and record crate.
3. Cover art serving endpoint /api/library/cover/{track_id} and fallback vinyl SVG placeholder.
4. Resurrected header buttons (Themes and Add-ons) in desktop_chrome.html.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db, insert_or_replace_features, insert_track
from vibeplay.web import create_app


@pytest.fixture
def test_env(tmp_path: Path):
    db_file = tmp_path / "test_ui.db"
    settings_file = tmp_path / "desktop_settings.json"
    init_db(db_file)
    cfg = Settings(db_path=db_file, desktop_settings_path=settings_file)
    app = create_app(db_path=db_file, settings=cfg)
    client = TestClient(app)
    return db_file, client


def test_screen_separation_and_panel_isolation(test_env):
    """Verify screens are encapsulated in separate .view-panel sections with correct initial visibility."""
    _, client = test_env
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Lo-Fi Lounge is active by default
    assert '<section id="view-lounge" class="view-panel active">' in html

    # 2. Master Crate & Table is isolated and hidden by default
    assert '<section id="view-library" class="view-panel" style="display: none;">' in html

    # 3. Vibe Generator / Smart Playlist Builder is isolated and hidden by default
    assert '<section id="view-generator" class="view-panel" style="display: none;">' in html

    # 4. Record Crate is isolated and hidden by default
    assert '<section id="view-crate" class="view-panel" style="display: none;">' in html

    # 5. Hardcoded mock "Lounge Listeners" markup stripped from template
    assert "Yuki M." not in html
    assert "Marcus L." not in html
    assert "Elena S." not in html
    assert "Sennheiser HD600" not in html
    assert "Audeze LCD-2" not in html
    assert "Focal Clear" not in html


def test_app_js_show_tab_logic():
    """Verify app.js showTab implementation hides all .view-panel and displays targeted view."""
    app_js_path = Path("src/vibeplay/static/app.js")
    content = app_js_path.read_text(encoding="utf-8")

    assert "function showTab(" in content
    assert "document.querySelectorAll('.view-panel')" in content
    assert "p.style.display = 'none'" in content
    assert "targetElement.style.display = 'block'" in content
    assert "targetElement.classList.add('active')" in content


def test_header_buttons_wiring(test_env):
    """Verify Themes and Add-ons buttons in desktop_chrome.html have required onclick triggers."""
    _, client = test_env
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # Header / Titlebar buttons
    assert "onclick=\"toggleSettingsDialog('theme')\"" in html
    assert 'onclick="openToyboxModal()"' in html
    assert 'id="chrome-btn-addons"' in html
    assert 'id="chrome-btn-themes"' in html


def test_cover_art_endpoint_and_fallback(test_env, tmp_path: Path):
    """Verify /api/library/cover/{track_id} returns image or 404 / vinyl placeholder fallback."""
    db_file, client = test_env

    # 1. Non-existent track -> 404
    resp_404 = client.get("/api/library/cover/99999")
    assert resp_404.status_code == 404

    # 2. Non-existent track with fallback=true -> returns SVG placeholder
    resp_fb = client.get("/api/library/cover/99999?fallback=true")
    assert resp_fb.status_code == 200
    assert resp_fb.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in resp_fb.text
    assert "VIBEPLAY" in resp_fb.text

    # 3. Insert real track with mock file and test artwork extraction
    test_flac = tmp_path / "song.flac"
    test_flac.write_bytes(b"dummy audio content")

    with get_connection(db_file) as conn:
        t_id = insert_track(
            conn,
            path=str(test_flac),
            title="High Res Flac",
            artist="Audiophile Trio",
            album="Studio Masters",
            duration=300,
            mtime=1.0,
            size=1024,
            file_hash="hash_art_test",
        )

    # When no embedded art in dummy file, returns 404 without fallback
    resp_no_art = client.get(f"/api/library/cover/{t_id}")
    assert resp_no_art.status_code == 404

    # With folder art present in parent directory (cover.jpg)
    cover_jpg = tmp_path / "cover.jpg"
    cover_jpg.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32)

    resp_art = client.get(f"/api/library/cover/{t_id}")
    assert resp_art.status_code == 200
    assert resp_art.headers["content-type"] == "image/jpeg"
    assert resp_art.content.startswith(b"\xff\xd8")


def test_library_table_and_record_crate_metadata_and_cover_bindings(test_env, tmp_path: Path):
    """Verify dynamic sample rate / bit depth bindings and cover art src in library table and record crate."""
    db_file, client = test_env

    with get_connection(db_file) as conn:
        t_id = insert_track(
            conn,
            path="/music/hires.flac",
            title="Symphony No. 5",
            artist="Philharmonic Orchestra",
            album="Classic Masters",
            duration=420,
            mtime=1.0,
            size=50000,
            file_hash="hash_hires_flac",
        )
        insert_or_replace_features(
            conn,
            track_id=t_id,
            analyzer_version="1.0.0",
            bpm=130.0,
            key="C",
            scale="minor",
            loudness=-6.0,
            danceability=0.5,
            energy=0.8,
            mood_scores_json="{}",
            embedding_blob=b"\x00" * 32,
        )

    # 1. Library table partial
    resp_table = client.get("/api/library/table")
    assert resp_table.status_code == 200
    table_html = resp_table.text

    assert f'src="/api/library/cover/{t_id}"' in table_html
    assert "onerror=\"this.onerror=null; this.src='/static/icons/vinyl_placeholder.svg';\"" in table_html
    # Dynamic sample rate & bit-depth display
    assert "96kHz / 24-bit" in table_html or "96 kHz" in table_html

    # 2. Record Crate in index
    resp_index = client.get("/")
    assert resp_index.status_code == 200
    index_html = resp_index.text

    assert f'src="/api/library/cover/{t_id}"' in index_html
    assert "vinyl_placeholder.svg" in index_html
