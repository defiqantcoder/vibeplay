"""Unit and integration tests for Phase 3: Verbose Hardware & DSP Settings Popover, Validation, and Persistence."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db
from vibeplay.desktop.settings import (
    DesktopSettings,
    load_desktop_settings,
    save_desktop_settings,
    update_desktop_settings,
)
from vibeplay.web import create_app


class TestDesktopSettingsValidation:
    """Tests for Pydantic validation across all 4 settings tabs."""

    def test_default_settings_are_valid(self) -> None:
        ds = DesktopSettings()
        assert ds.alsa_device == "hw:0,0"
        assert ds.alsa_exclusive_lock is True
        assert ds.alsa_buffer_frames == 128
        assert ds.alsa_period_count == 2
        assert ds.alsa_sample_rate_lock == "auto"
        assert ds.dpc_watchdog_enabled is True
        assert ds.dsp_profile == "pure-bitperfect"
        assert ds.peq_profile == "none"
        assert ds.peq_preamp_auto is True
        assert ds.peq_preamp_db == -5.5
        assert ds.spatial_enabled is False
        assert ds.spatial_mode == "stereo_direct"
        assert ds.analyzer_backend == "essentia"
        assert ds.analyzer_workers == 4
        assert ds.analyzer_window_seconds == 60.0
        assert ds.analyzer_fallback_enabled is True
        assert ds.mood_confidence_threshold == 0.50
        assert ds.theme_id == "god-of-ink"
        assert ds.custom_accent_color == "#6874a6"
        assert ds.contrast_mode == "standard"

    def test_alsa_transport_validation(self) -> None:
        valid = DesktopSettings(
            alsa_device="plughw:1,0",
            alsa_exclusive_lock=False,
            alsa_buffer_frames=64,
            alsa_period_count=4,
            alsa_sample_rate_lock="96000",
            dpc_watchdog_enabled=False,
        )
        assert valid.alsa_device == "plughw:1,0"
        assert valid.alsa_buffer_frames == 64
        assert valid.alsa_period_count == 4
        assert valid.alsa_sample_rate_lock == "96000"

        with pytest.raises(ValidationError):
            DesktopSettings(alsa_device="invalid_device; rm -rf /")

        with pytest.raises(ValidationError):
            DesktopSettings(alsa_buffer_frames=100)  # Not a power-of-two frame size

        with pytest.raises(ValidationError):
            DesktopSettings(alsa_period_count=1)  # Below minimum 2 periods

        with pytest.raises(ValidationError):
            DesktopSettings(alsa_sample_rate_lock="12345")

    def test_dsp_and_signal_chain_validation(self) -> None:
        valid = DesktopSettings(
            dsp_profile="spatial-headphones",
            peq_profile="7hz_zero_2",
            peq_preamp_auto=True,
            peq_preamp_db=-6.2,
            spatial_enabled=True,
            spatial_mode="3d_binaural",
        )
        assert valid.dsp_profile == "spatial-headphones"
        assert valid.peq_profile == "7hz_zero_2"
        assert valid.peq_preamp_db == -6.2

        with pytest.raises(ValidationError):
            DesktopSettings(dsp_profile="unknown-route")

        with pytest.raises(ValidationError):
            DesktopSettings(peq_profile="nonexistent_headphone_xyz")

        with pytest.raises(ValidationError):
            DesktopSettings(peq_preamp_db=3.0)  # Positive preamp prohibited (clipping risk)

        with pytest.raises(ValidationError):
            DesktopSettings(spatial_mode="dolby_atmos_fake")

    def test_analyzer_feature_extraction_validation(self) -> None:
        valid = DesktopSettings(
            analyzer_backend="librosa",
            analyzer_workers=8,
            analyzer_window_seconds=45.0,
            analyzer_fallback_enabled=False,
            mood_confidence_threshold=0.75,
        )
        assert valid.analyzer_backend == "librosa"
        assert valid.analyzer_workers == 8
        assert valid.mood_confidence_threshold == 0.75

        with pytest.raises(ValidationError):
            DesktopSettings(analyzer_backend="pytorch_invalid")

        with pytest.raises(ValidationError):
            DesktopSettings(analyzer_workers=0)

        with pytest.raises(ValidationError):
            DesktopSettings(analyzer_workers=64)

        with pytest.raises(ValidationError):
            DesktopSettings(analyzer_window_seconds=5.0)

        with pytest.raises(ValidationError):
            DesktopSettings(mood_confidence_threshold=0.99)

    def test_theme_engine_validation(self) -> None:
        valid = DesktopSettings(
            theme_id="obsidian",
            custom_accent_color="#A855F7",
            contrast_mode="high-contrast",
        )
        assert valid.theme_id == "obsidian"
        assert valid.custom_accent_color == "#a855f7"
        assert valid.contrast_mode == "high-contrast"

        with pytest.raises(ValidationError):
            DesktopSettings(theme_id="neon-pink-nonexistent")

        with pytest.raises(ValidationError):
            DesktopSettings(custom_accent_color="rgb(255,0,0)")

        with pytest.raises(ValidationError):
            DesktopSettings(contrast_mode="ultra-bright")


class TestDesktopSettingsPersistence:
    """Tests for atomic JSON config file persistence."""

    def test_save_and_load_roundtrip_with_secure_permissions(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config" / "desktop_settings.json"
        original = DesktopSettings(
            alsa_device="hw:0,3",
            alsa_buffer_frames=256,
            dsp_profile="receiver-passthrough",
            peq_profile="sennheiser_hd600",
            analyzer_workers=8,
            mood_confidence_threshold=0.65,
            theme_id="mint-city",
            custom_accent_color="#14b8a6",
            contrast_mode="high-contrast",
        )
        saved_path = save_desktop_settings(original, cfg_file)
        assert saved_path == cfg_file
        assert cfg_file.exists()

        mode = stat.S_IMODE(cfg_file.stat().st_mode)
        assert mode == 0o600

        loaded = load_desktop_settings(cfg_file)
        assert loaded == original

    def test_partial_update_and_corrupt_file_fallback(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "desktop_settings.json"
        updated = update_desktop_settings(
            {"alsa_buffer_frames": 512, "theme_id": "wine"}, cfg_file
        )
        assert updated.alsa_buffer_frames == 512
        assert updated.theme_id == "wine"
        assert updated.alsa_device == "hw:0,0"

        # Corrupt JSON should gracefully fall back to defaults
        cfg_file.write_text("{corrupt json", encoding="utf-8")
        fallback = load_desktop_settings(cfg_file)
        assert fallback == DesktopSettings()


class TestPhase3WebApiAndLiveState:
    """Tests for /api/settings, /api/dsp/peq/*, and live runtime state updates without reload."""

    @pytest.fixture
    def client_and_paths(self, tmp_path: Path) -> tuple[TestClient, Path, Path, Settings]:
        db_file = tmp_path / "phase3_test.db"
        cfg_file = tmp_path / "desktop_settings.json"
        init_db(db_file)
        settings = Settings(db_path=db_file, desktop_settings_path=cfg_file)
        app = create_app(db_path=db_file, settings=settings)
        return TestClient(app), db_file, cfg_file, settings

    def test_get_and_post_settings_updates_state_and_persists(
        self, client_and_paths: tuple[TestClient, Path, Path, Settings]
    ) -> None:
        client, db_file, cfg_file, settings = client_and_paths

        # 1. GET initial settings
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["settings"]["alsa_device"] == "hw:0,0"
        assert "7hz_zero_2" in body["peq_presets"]

        # 2. POST partial settings update across all 4 tabs
        update_payload = {
            "alsa_device": "hw:0,4",
            "alsa_exclusive_lock": False,
            "alsa_buffer_frames": 256,
            "alsa_period_count": 3,
            "alsa_sample_rate_lock": "192000",
            "dpc_watchdog_enabled": False,
            "dsp_profile": "spatial-headphones",
            "peq_profile": "7hz_zero_2",
            "peq_preamp_auto": True,
            "spatial_enabled": True,
            "analyzer_backend": "librosa",
            "analyzer_workers": 8,
            "analyzer_window_seconds": 90.0,
            "analyzer_fallback_enabled": False,
            "mood_confidence_threshold": 0.70,
            "theme_id": "swimming-with-the-whales",
            "custom_accent_color": "#0284c7",
            "contrast_mode": "high-contrast",
        }
        post_resp = client.post("/api/settings", json=update_payload)
        assert post_resp.status_code == 200
        saved = post_resp.json()["settings"]
        assert saved["alsa_device"] == "hw:0,4"
        assert saved["alsa_buffer_frames"] == 256
        assert saved["alsa_period_count"] == 3
        assert saved["peq_profile"] == "7hz_zero_2"
        assert saved["peq_preamp_db"] < 0.0  # Automatically calculated negative preamp headroom
        assert saved["spatial_mode"] == "3d_binaural"
        assert saved["theme_id"] == "swimming-with-the-whales"
        assert saved["contrast_mode"] == "high-contrast"

        # Verify runtime Settings object was updated in-place without reload
        assert settings.analyzer_backend == "librosa"
        assert settings.analyzer_workers == 8
        assert settings.analyzer_window_seconds == 90.0
        assert settings.analyzer_fallback_enabled is False
        assert settings.mood_confidence_threshold == 0.70

        # Verify file was persisted to disk and reloads into a fresh app instance
        assert cfg_file.exists()
        fresh_settings = Settings(db_path=db_file, desktop_settings_path=cfg_file)
        fresh_app = create_app(db_path=db_file, settings=fresh_settings)
        assert fresh_settings.mood_confidence_threshold == 0.70
        fresh_client = TestClient(fresh_app)
        assert fresh_client.get("/api/settings").json()["settings"]["theme_id"] == "swimming-with-the-whales"

    def test_post_settings_rejects_invalid_values_with_422(
        self, client_and_paths: tuple[TestClient, Path, Path, Settings]
    ) -> None:
        client, _, _, _ = client_and_paths

        resp = client.post(
            "/api/settings",
            json={"alsa_buffer_frames": 999, "custom_accent_color": "not-a-hex"},
        )
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_peq_presets_list_and_apply_endpoints(
        self, client_and_paths: tuple[TestClient, Path, Path, Settings]
    ) -> None:
        client, _, _, _ = client_and_paths

        presets_resp = client.get("/api/dsp/peq/presets")
        assert presets_resp.status_code == 200
        presets = presets_resp.json()["presets"]
        preset_ids = {p["id"] for p in presets}
        assert {"none", "7hz_zero_2", "moondrop_blessing_2", "sennheiser_hd600", "apple_airpods_pro_2"}.issubset(
            preset_ids
        )

        apply_resp = client.post("/api/dsp/peq/apply", json={"preset": "sennheiser_hd600"})
        assert apply_resp.status_code == 200
        applied = apply_resp.json()
        assert applied["status"] == "applied"
        assert applied["peq_profile"] == "sennheiser_hd600"
        assert applied["peq_preamp_db"] < 0.0
        assert applied["filters_count"] > 0

        # Bypass resets auto preamp to 0.0 dB
        bypass_resp = client.post("/api/dsp/peq/apply", json={"preset": "none"})
        assert bypass_resp.status_code == 200
        assert bypass_resp.json()["peq_preamp_db"] == 0.0

    def test_mood_confidence_threshold_dynamically_filters_library_without_reload(
        self, client_and_paths: tuple[TestClient, Path, Path, Settings]
    ) -> None:
        client, db_file, _, _ = client_and_paths

        with get_connection(db_file) as conn:
            conn.execute(
                """
                INSERT INTO tracks (id, path, mtime, size, hash, duration, title, artist, album, status)
                VALUES (1, '/music/track1.flac', 1000.0, 5000, 'hash_track_1', 180.0, 'Borderline Happy Track', 'Test Artist', 'Test Album', 'active')
                """
            )
            conn.execute(
                """
                INSERT INTO features (track_id, bpm, key, scale, energy, danceability, loudness, mood_scores, analyzer_version)
                VALUES (1, 124.0, 'C', 'major', 0.8, 0.7, -9.0, ?, 'test-1.0')
                """,
                (json.dumps({"happy": 0.60}),),
            )
            conn.commit()

        # Default threshold is 0.50 -> track (0.60 happy) appears
        r1 = client.get("/api/library/table?mood=happy")
        assert r1.status_code == 200
        assert "Borderline Happy Track" in r1.text

        # Raise mood_confidence_threshold to 0.75 via /api/settings -> track is filtered out immediately
        client.post("/api/settings", json={"mood_confidence_threshold": 0.75})
        r2 = client.get("/api/library/table?mood=happy")
        assert r2.status_code == 200
        assert "Borderline Happy Track" not in r2.text

    def test_settings_dialog_renders_all_phase3_controls(
        self, client_and_paths: tuple[TestClient, Path, Path, Settings]
    ) -> None:
        client, _, _, _ = client_and_paths
        html = client.get("/").text

        # Tab 1: ALSA Hardware Transport
        assert 'id="cfg-alsa-device"' in html
        assert 'id="cfg-exclusive-lock"' in html
        assert 'id="cfg-buffer-size"' in html
        assert 'id="cfg-period-count"' in html
        assert 'id="cfg-sample-rate"' in html
        assert 'id="cfg-dpc-watchdog"' in html

        # Tab 2: DSP & Signal Chain
        assert 'id="cfg-peq-profile"' in html
        assert 'id="cfg-preamp-toggle"' in html
        assert 'id="cfg-spatial-toggle"' in html

        # Tab 3: Essentia Feature Extraction
        assert 'id="cfg-analyzer-backend"' in html
        assert 'id="cfg-workers"' in html
        assert 'id="cfg-window-sec"' in html
        assert 'id="cfg-mood-threshold"' in html
        assert 'id="cfg-analyzer-fallback"' in html

        # Tab 4: Theme Engine
        assert 'id="cfg-custom-accent"' in html
        assert 'id="cfg-custom-accent-picker"' in html
        assert 'id="cfg-contrast-mode"' in html
        assert ":user-invalid" in html

    def test_spatial_toggle_persists_state_without_mocks(
        self, client_and_paths: tuple[TestClient, Path, Path, Settings]
    ) -> None:
        client, _, cfg_file, _ = client_and_paths

        r1 = client.post("/api/dsp/spatial/toggle")
        assert r1.status_code == 200
        assert r1.json()["mode"] in {"spatial_binaural", "3d_binaural"}
        assert load_desktop_settings(cfg_file).spatial_enabled is True

        r2 = client.post("/api/dsp/spatial/toggle")
        assert r2.status_code == 200
        assert r2.json()["mode"] == "stereo_direct"
        assert load_desktop_settings(cfg_file).spatial_enabled is False
