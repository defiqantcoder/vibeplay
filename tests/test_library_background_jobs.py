"""Tests for asynchronous background library scanning, enrichment, analysis, and jobs API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import init_db
from vibeplay.jobs import (
    complete_job_run,
    create_job_run,
    fail_job_run,
    get_active_jobs,
    get_recent_jobs,
    is_job_type_running,
    update_job_progress,
)
from vibeplay.web import create_app


@pytest.fixture
def test_env(tmp_path: Path):
    db_path = tmp_path / "test_jobs.db"
    settings_path = tmp_path / "desktop_settings.json"
    music_dir = tmp_path / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    init_db(db_path)

    settings = Settings(
        db_path=db_path,
        desktop_settings_path=settings_path,
        music_dir=music_dir,
    )
    app = create_app(db_path=db_path, settings=settings, api_key="test-token")
    client = TestClient(app)
    return {
        "db_path": db_path,
        "settings": settings,
        "client": client,
        "music_dir": music_dir,
        "headers": {"X-API-Key": "test-token"},
    }


def test_job_persistence_lifecycle(test_env):
    db_path = test_env["db_path"]

    # 1. Initially no active jobs
    assert get_active_jobs(db_path) == []
    assert not is_job_type_running(db_path, "scan")

    # 2. Create job
    job_id = create_job_run(db_path, "scan", total_items=10)
    assert job_id is not None
    assert is_job_type_running(db_path, "scan")

    # Check active jobs list
    active = get_active_jobs(db_path)
    assert len(active) == 1
    assert active[0]["id"] == job_id
    assert active[0]["percent"] == 0.0

    # 3. Update progress
    update_job_progress(db_path, job_id, processed_items=5, current_item_name="track01.flac")
    active = get_active_jobs(db_path)
    assert len(active) == 1
    assert active[0]["processed_items"] == 5
    assert active[0]["percent"] == 50.0
    assert active[0]["current_item_name"] == "track01.flac"

    # 4. Complete job
    complete_job_run(db_path, job_id, total_items=10)
    assert get_active_jobs(db_path) == []
    assert not is_job_type_running(db_path, "scan")

    recent = get_recent_jobs(db_path, limit=5)
    assert len(recent) == 1
    assert recent[0]["status"] == "completed"
    assert recent[0]["percent"] == 100.0


def test_job_failure_lifecycle(test_env):
    db_path = test_env["db_path"]
    job_id = create_job_run(db_path, "enrich", total_items=5)
    fail_job_run(db_path, job_id, "Network timeout connecting to MusicBrainz")

    assert get_active_jobs(db_path) == []
    recent = get_recent_jobs(db_path)
    assert len(recent) == 1
    assert recent[0]["status"] == "failed"
    assert "Network timeout" in recent[0]["error_message"]


def test_api_jobs_status_and_progress_widget(test_env):
    client = test_env["client"]
    headers = test_env["headers"]
    db_path = test_env["db_path"]

    # Query initial status
    res = client.get("/api/jobs/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["active_count"] == 0

    # Query progress widget in idle state
    res_widget = client.get("/api/jobs/progress-widget", headers=headers)
    assert res_widget.status_code == 200
    assert "job-progress-wrapper" in res_widget.text
    assert "idle" in res_widget.text

    # Create active job
    job_id = create_job_run(db_path, "analyze", total_items=20)
    update_job_progress(db_path, job_id, processed_items=10, current_item_name="nocturne.wav")

    # Query status again
    res = client.get("/api/jobs/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["active_count"] == 1
    assert data["active_jobs"][0]["job_type"] == "analyze"
    assert data["active_jobs"][0]["percent"] == 50.0

    # Query progress widget in active state
    res_widget = client.get("/api/jobs/progress-widget", headers=headers)
    assert res_widget.status_code == 200
    assert "Analyzing Vibe Features" in res_widget.text
    assert "50.0%" in res_widget.text
    assert "nocturne.wav" in res_widget.text


def test_api_library_scan_trigger(test_env):
    client = test_env["client"]
    headers = test_env["headers"]
    music_dir = test_env["music_dir"]

    with patch("vibeplay.scanner.scan_directory") as mock_scan:
        mock_scan.return_value = MagicMock(total=0, new=0, updated=0, unchanged=0)
        res = client.post(
            "/api/library/scan",
            json={"path": str(music_dir)},
            headers=headers,
        )
        assert res.status_code in (200, 202)
        data = res.json()
        assert "job_id" in data
        assert data["status"] in ("running", "already_running")


def test_api_desktop_browse_folder(test_env):
    client = test_env["client"]
    headers = test_env["headers"]

    with patch("vibeplay.desktop.dialogs.choose_directory_dialog", return_value="/home/test/Music"):
        res = client.post("/api/desktop/browse-folder", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["path"] == "/home/test/Music"
        assert data["cancelled"] is False

    with patch("vibeplay.desktop.dialogs.choose_directory_dialog", return_value=None):
        res = client.post("/api/desktop/browse-folder", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["path"] is None
        assert data["cancelled"] is True


def test_custom_audio_output_dropdown_rendered(test_env):
    client = test_env["client"]
    headers = test_env["headers"]

    # Ensure index page renders custom audio dropdown instead of raw select
    res = client.get("/?token=test-token")
    assert res.status_code == 200
    assert "audio-output-dropdown-container" in res.text
    assert "btn-audio-output" in res.text
    assert "audio-output-menu" in res.text

    # Switch audio output
    res_post = client.post(
        "/api/player/output",
        data={"profile": "PipeWire Sound Server"},
        headers=headers,
    )
    assert res_post.status_code == 200
    assert "audio-output-dropdown-container" in res_post.text
    assert "PipeWire Sound Server" in res_post.text
