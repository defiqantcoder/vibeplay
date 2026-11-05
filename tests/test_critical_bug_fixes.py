"""Test critical bug fixes: crash prevention, safe settings, dynamic DAC detection, and audio routing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import init_db
from vibeplay.desktop.settings import DesktopSettings, load_desktop_settings
from vibeplay.player import (
    get_active_output_profile,
    get_output_profiles,
    play_track,
    set_output_profile,
)
from vibeplay.routers.root import safe_get_setting as root_safe_get
from vibeplay.routers.settings import safe_get_setting as settings_safe_get
from vibeplay.web import create_app


@pytest.fixture
def app_env(tmp_path: Path):
    db_file = tmp_path / "test_critical.db"
    settings_file = tmp_path / "desktop_settings.json"
    init_db(db_file)
    cfg = Settings(db_path=db_file, desktop_settings_path=settings_file)
    app = create_app(db_path=db_file, settings=cfg)
    client = TestClient(app)
    return client, db_file, settings_file, cfg


def test_safe_get_setting_handles_desktop_settings_and_dicts():
    """Verify safe_get_setting works transparently across dicts, DesktopSettings, and None."""
    # Test DesktopSettings instance
    ds = DesktopSettings(gemini_api_key="test-key-123", gemini_model="gemini-3.8-flash")
    assert ds.get("gemini_api_key", "") == "test-key-123"
    assert ds["gemini_api_key"] == "test-key-123"
    assert ds.get("non_existent", "fallback") == "fallback"
    assert settings_safe_get(ds, "gemini_api_key", "") == "test-key-123"
    assert root_safe_get(ds, "gemini_api_key", "") == "test-key-123"

    # Test plain dict
    d = {"gemini_api_key": "dict-key-456"}
    assert settings_safe_get(d, "gemini_api_key", "") == "dict-key-456"
    assert settings_safe_get(d, "missing_key", "") == ""

    # Test None
    assert settings_safe_get(None, "gemini_api_key", "") == ""


def test_missing_or_corrupt_config_file_fallbacks_gracefully(tmp_path: Path):
    """Verify missing or corrupt configuration file returns defaults without uncaught exceptions."""
    non_existent = tmp_path / "does_not_exist.json"
    ds = load_desktop_settings(non_existent)
    assert isinstance(ds, DesktopSettings)
    assert ds.get("gemini_api_key", "") == ""
    assert ds.gemini_model == "gemini-3.8-flash"

    # Corrupted JSON
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{broken json syntax: [")
    ds_corrupt = load_desktop_settings(corrupt_file)
    assert isinstance(ds_corrupt, DesktopSettings)
    assert ds_corrupt.get("gemini_api_key", "") == ""


def test_gemini_model_upgrades_deprecated_versions():
    """Verify deprecated gemini models (2.5, 1.5) are automatically upgraded to current 3.8/3-pro."""
    ds = DesktopSettings.model_validate({"gemini_model": "gemini-2.5-flash"})
    assert ds.gemini_model == "gemini-3.8-flash"

    ds_pro = DesktopSettings.model_validate({"gemini_model": "gemini-2.5-pro"})
    assert ds_pro.gemini_model == "gemini-3-pro-preview"


def test_settings_modal_html_endpoint(app_env):
    """Verify settings modal endpoints return HTTP 200 valid HTML so webview does not abort."""
    client, _, _, _ = app_env

    # 1. Direct modal endpoint
    resp = client.get("/api/settings/modal")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert 'id="settings-dialog"' in resp.text
    assert "Google Gemini API Key" in resp.text
    assert "gemini-3.8-flash" in resp.text

    # 2. HTMX / view=modal query
    resp_htmx = client.get("/api/settings?view=modal", headers={"HX-Request": "true"})
    assert resp_htmx.status_code == 200
    assert "text/html" in resp_htmx.headers["content-type"]
    assert 'id="settings-dialog"' in resp_htmx.text

    # 3. Dedicated Gemini API key endpoint
    resp_key = client.get("/api/settings/api-key")
    assert resp_key.status_code == 200
    data = resp_key.json()
    assert "gemini_api_key" in data
    assert "gemini_model" in data


def test_dynamic_dac_detection_parses_proc_asound_cards(tmp_path: Path):
    """Verify /proc/asound/cards dynamically detects USB DACs such as FiiO KA15 and Letshuoer."""
    cards_sample = (
        " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n"
        "                      HDA Intel PCH at 0x... irq 123\n"
        " 1 [KA15           ]: USB-Audio - FiiO KA15\n"
        "                      FiiO FiiO KA15 at usb-0000:00:14.0-1, high speed\n"
        " 2 [DT01           ]: USB-Audio - Letshuoer DT01\n"
        "                      LETSHUOER LETSHUOER DT01 at usb-0000:00:14.0-2, high speed\n"
    )

    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=cards_sample):
        profiles = get_output_profiles()
        assert any("FiiO KA15" in p["name"] for p in profiles)
        assert any("Letshuoer" in p["name"] for p in profiles)
        assert any("PipeWire Sound Server" in p["name"] for p in profiles)
        assert any("Pure Bit-Perfect (Direct ALSA)" in p["name"] for p in profiles)


def test_output_selection_updates_active_checkmark_and_commits_sink(app_env):
    """Verify selecting an output profile commits the route and returns updated output_switcher snippet with active checkmark."""
    client, _, _, _ = app_env

    # Post new profile
    target = "Pure Bit-Perfect (Direct ALSA)"
    resp = client.post("/api/player/output", data={"profile": target})
    assert resp.status_code == 200
    html = resp.text

    # Verify updated active checkmark card in output_switcher snippet
    assert 'id="output-switcher-popover"' in html
    assert "output-device-card active" in html
    assert "Pure Bit-Perfect" in html
    assert "Active" in html

    # Verify out-of-band updates
    assert 'id="transport-footer-container"' in html
    assert 'hx-swap-oob="true"' in html
    assert 'id="header-playing-on-text"' in html

    # Verify active profile in backend
    assert get_active_output_profile() == target


def test_play_track_falls_back_to_direct_audio_player_on_mpd_failure(tmp_path: Path):
    """Verify play_track triggers fallback playback without swallowing exceptions when MPD fails or reports device error."""
    db_file = tmp_path / "test_player.db"
    init_db(db_file)
    from vibeplay.db import get_connection

    # Insert a dummy track
    track_path = str(tmp_path / "song.flac")
    Path(track_path).touch()
    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tracks (path, mtime, size, hash, duration, status) VALUES (?, 1000.0, 1024, 'hash1', 180.0, 'active')",
            (track_path,),
        )
        conn.commit()
        track_id = cursor.lastrowid

    # 1. MPD connection throws exception
    with patch("vibeplay.player.get_mpd_transport", side_effect=Exception("MPD daemon unavailable")), \
         patch("vibeplay.player._start_fallback_playback") as mock_fallback:
        res = play_track(db_file, track_id)
        assert res["state"] == "play"
        assert res["fallback"] is True
        mock_fallback.assert_called_once()

    # 2. MPD connects but status reports error / device lock failure
    mock_transport = MagicMock()
    mock_transport.status.return_value = {"state": "stop", "error": "problems opening audio device hw:0,0"}
    with patch("vibeplay.player.get_mpd_transport") as mock_get_trans, \
         patch("vibeplay.player._start_fallback_playback") as mock_fallback2:
        mock_get_trans.return_value.__enter__.return_value = mock_transport
        res2 = play_track(db_file, track_id)
        assert res2["fallback"] is True
        mock_fallback2.assert_called_once()


def test_volume_controls_in_app_js_are_debounced_by_50ms():
    """Verify app.js applies optimistic updates and debounces volume requests by 50ms."""
    app_js = Path("src/vibeplay/static/app.js").read_text(encoding="utf-8")

    assert "volumeDebounceTimer" in app_js
    assert "applyVolumeOptimistic" in app_js
    assert "setTimeout" in app_js
    assert "50" in app_js
    assert "gemini-3.8-flash" in app_js
    assert "gemini-2.5-flash" not in app_js
