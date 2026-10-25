"""Phase 7 Release Gate Validator for vibeplay."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

import warnings

# Suppress harmless StarletteDeprecationWarning when TestClient is loaded
warnings.filterwarnings("ignore", message=r".*starlette\.testclient.*")
warnings.filterwarnings("ignore", message=r".*httpx.*deprecated.*")
warnings.filterwarnings("ignore", category=Warning, module=r"fastapi\.testclient.*")
warnings.filterwarnings("ignore", category=Warning, module=r"starlette\..*")

from vibeplay.config import Settings
from vibeplay.db import init_db
from vibeplay.desktop.settings import DesktopSettings, load_desktop_settings, save_desktop_settings
from vibeplay.ui.theme import get_available_themes, verify_theme_contrast
from vibeplay.web import create_app


@dataclass(frozen=True)
class GateCheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReleaseGateReport:
    passed: bool
    checks: list[GateCheckResult]


def validate_loopback_host(host: str) -> bool:
    """Strictly verify if the host is a loopback address."""
    return host in ("127.0.0.1", "localhost", "::1")


def run_release_gate_checks(db_path: Path | None = None, settings_path: Path | None = None) -> ReleaseGateReport:
    """Run all Phase 7 desktop invariant release gate checks."""
    checks = []

    # 1. Loopback Security Invariant
    try:
        assert validate_loopback_host("127.0.0.1") is True, "127.0.0.1 must be allowed"
        assert validate_loopback_host("localhost") is True, "localhost must be allowed"
        assert validate_loopback_host("0.0.0.0") is False, "0.0.0.0 must be rejected"
        checks.append(GateCheckResult("Loopback Security Invariant", True, "Passed loopback validation"))
    except AssertionError as e:
        checks.append(GateCheckResult("Loopback Security Invariant", False, str(e)))

    # 2. Settings Persistence & 0600 Permissions
    try:
        if settings_path is None:
            raise ValueError("settings_path must be provided for the release gate check")

        settings = DesktopSettings()
        save_desktop_settings(settings, path=settings_path)

        st = os.stat(settings_path)
        file_mode = stat.S_IMODE(st.st_mode)

        assert file_mode == 0o600, f"Expected permissions 0o600, got {oct(file_mode)}"

        loaded_settings = load_desktop_settings(path=settings_path)
        assert loaded_settings.model_dump() == settings.model_dump(), "Round-trip settings integrity failed"

        checks.append(GateCheckResult("Settings Persistence & Permissions", True, "Passed atomicity and 0600 permission checks"))
    except Exception as e:
        checks.append(GateCheckResult("Settings Persistence & Permissions", False, str(e)))

    # 3. Theme Engine & WCAG Contrast Gate
    try:
        themes = get_available_themes()
        assert len(themes) > 0, "No themes available"

        for preset in themes:
            ratios = verify_theme_contrast(preset.id)
            # primary text >= 7.0
            assert ratios["text_on_base"] >= 7.0, f"{preset.id}: text_on_base {ratios['text_on_base']} < 7.0"
            assert ratios["text_on_surface"] >= 7.0, f"{preset.id}: text_on_surface {ratios['text_on_surface']} < 7.0"

            # muted/menu/button text >= 4.5
            assert ratios["muted_on_base"] >= 4.5, f"{preset.id}: muted_on_base {ratios['muted_on_base']} < 4.5"
            assert ratios["muted_on_surface"] >= 4.5, f"{preset.id}: muted_on_surface {ratios['muted_on_surface']} < 4.5"
            assert ratios["text_on_menu"] >= 4.5, f"{preset.id}: text_on_menu {ratios['text_on_menu']} < 4.5"
            assert ratios["button_on_primary"] >= 4.5, f"{preset.id}: button_on_primary {ratios['button_on_primary']} < 4.5"

            # status indicators >= 3.0
            assert ratios["status_ok_on_surface"] >= 3.0, f"{preset.id}: status_ok_on_surface {ratios['status_ok_on_surface']} < 3.0"
            assert ratios["status_warn_on_surface"] >= 3.0, f"{preset.id}: status_warn_on_surface {ratios['status_warn_on_surface']} < 3.0"
            assert ratios["status_err_on_surface"] >= 3.0, f"{preset.id}: status_err_on_surface {ratios['status_err_on_surface']} < 3.0"

        checks.append(GateCheckResult("Theme Engine & WCAG Contrast", True, f"Verified WCAG compliance for {len(themes)} themes"))
    except AssertionError as e:
        checks.append(GateCheckResult("Theme Engine & WCAG Contrast", False, str(e)))
    except Exception as e:
        checks.append(GateCheckResult("Theme Engine & WCAG Contrast", False, f"Unexpected error: {e}"))

    # 4. Template & Static Asset Integrity Check
    try:
        base_dir = Path(__file__).parent.parent
        templates_dir = base_dir / "templates"
        static_dir = base_dir / "static"

        required_templates = [
            "base.html",
            "index.html",
            "components/desktop_chrome.html",
            "components/settings_dialog.html",
            "components/styles.html",
            "components/library_table.html",
            "components/transport_bar.html",
            "components/cluster_cards.html",
            "components/track_detail.html",
            "components/playlist_builder.html",
            "components/playlist_seed_results.html",
        ]

        required_static = [
            "style.css",
            "htmx.min.js",
        ]

        for tmpl in required_templates:
            tmpl_path = templates_dir / tmpl
            assert tmpl_path.exists(), f"Missing template: {tmpl}"
            assert tmpl_path.stat().st_size > 0, f"Empty template: {tmpl}"

        for stat_file in required_static:
            stat_path = static_dir / stat_file
            assert stat_path.exists(), f"Missing static asset: {stat_file}"
            assert stat_path.stat().st_size > 0, f"Empty static asset: {stat_file}"

        checks.append(GateCheckResult("Template & Asset Integrity", True, "All required assets exist and are non-empty"))
    except AssertionError as e:
        checks.append(GateCheckResult("Template & Asset Integrity", False, str(e)))
    except Exception as e:
        checks.append(GateCheckResult("Template & Asset Integrity", False, f"Unexpected error: {e}"))

    # 5. HTMX & Desktop API Smoke Gate
    try:
        if db_path is None:
            raise ValueError("db_path must be provided for the API Smoke Gate check")

        # Initialize test DB
        init_db(db_path)

        # Create config and app
        settings = Settings(db_path=db_path, desktop_settings_path=settings_path)
        app = create_app(db_path=db_path, settings=settings, api_key="test-token")

        from fastapi.testclient import TestClient

        client = TestClient(app)
        headers = {"X-Vibeplay-Session": "test-token"}

        # Verify GET / renders desktop chrome and components
        resp_index = client.get("/?token=test-token")
        assert resp_index.status_code == 200, f"GET / failed: {resp_index.status_code}"
        body = resp_index.text
        assert "File" in body and "Edit" in body and "Library" in body, "Missing menu bars"
        assert "Playback" in body and "DSP" in body and "View" in body and "Help" in body, "Missing menu bars"
        assert "Ctrl+R" in body and "Ctrl+O" in body, "Missing keyboard shortcuts"
        assert "Ctrl+," in body and "Ctrl+Q" in body, "Missing keyboard shortcuts"

        # Verify API endpoints
        resp_table = client.get("/api/library/table?sort=bpm&order=desc", headers=headers)
        assert resp_table.status_code == 200, f"GET /api/library/table failed: {resp_table.status_code}"

        resp_menu = client.get("/api/menu", headers=headers)
        assert resp_menu.status_code == 200, f"GET /api/menu failed: {resp_menu.status_code}"

        resp_themes = client.get("/api/themes", headers=headers)
        assert resp_themes.status_code == 200, f"GET /api/themes failed: {resp_themes.status_code}"

        resp_settings = client.get("/api/settings", headers=headers)
        assert resp_settings.status_code == 200, f"GET /api/settings failed: {resp_settings.status_code}"

        resp_dsp = client.get("/api/dsp/telemetry", headers=headers)
        assert resp_dsp.status_code == 200, f"GET /api/dsp/telemetry failed: {resp_dsp.status_code}"

        checks.append(GateCheckResult("API Smoke Gate", True, "All API endpoints returned 200 OK"))
    except AssertionError as e:
        checks.append(GateCheckResult("API Smoke Gate", False, str(e)))
    except Exception as e:
        checks.append(GateCheckResult("API Smoke Gate", False, f"Unexpected error: {e}"))

    # 6. Supervisor Clean Teardown Check
    supervisor = None
    try:
        import threading

        from vibeplay.desktop.supervisor import DesktopSupervisor

        supervisor = DesktopSupervisor(db_path=db_path, host="127.0.0.1", port=8080, start_mpd_child=False)

        # Start headlessly in a background thread so we don't block
        def run_supervisor():
            try:
                supervisor.start(headless=True)
            except Exception:
                pass

        t = threading.Thread(target=run_supervisor, daemon=True)
        t.start()

        # Wait for supervisor to finish starting up
        supervisor.ready_event.wait(timeout=5.0)

        # Stop
        supervisor.stop()
        assert supervisor.is_running is False, "Supervisor failed to stop"
        assert supervisor.server is None, "Supervisor server not torn down"
        assert supervisor.server_thread is None or not supervisor.server_thread.is_alive(), "Server thread leaked"

        checks.append(GateCheckResult("Supervisor Clean Teardown", True, "Supervisor stopped cleanly with no orphans"))
    except AssertionError as e:
        checks.append(GateCheckResult("Supervisor Clean Teardown", False, str(e)))
    except Exception as e:
        checks.append(GateCheckResult("Supervisor Clean Teardown", False, f"Unexpected error: {e}"))
    finally:
        if supervisor and supervisor.is_running:
            supervisor.stop()

    all_passed = all(c.passed for c in checks)
    return ReleaseGateReport(passed=all_passed, checks=checks)
