"""Tests for Live SSE Audio Visualizer and Dynamic Telemetry Deck."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db
from vibeplay.desktop.telemetry_stream import (
    TelemetryMonitor,
    TelemetrySnapshot,
    format_sse_event,
)
from vibeplay.web import create_app


@pytest.fixture
def isolated_telemetry_env(tmp_path: Path):
    db_path = tmp_path / "telemetry_test.db"
    settings_path = tmp_path / "desktop_settings.json"
    music_dir = tmp_path / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    init_db(db_path)

    settings = Settings(
        db_path=db_path,
        desktop_settings_path=settings_path,
        music_dir=music_dir,
    )
    return db_path, settings_path, music_dir, settings


def test_telemetry_snapshot_and_monitor_events() -> None:
    """Verify TelemetryMonitor event detection and delta emission."""
    monitor = TelemetryMonitor()

    s1 = TelemetrySnapshot(
        xruns=0,
        bit_perfect_locked=True,
        sample_rate_hz=96000,
        bit_depth=24,
        alsa_device="hw:0,0",
        dsp_profile="pure-bitperfect",
        spatial_enabled=False,
        current_track_id=1,
        current_track_title="First Light",
        current_track_artist="Acoustic",
        service_healthy=True,
        buffer_frames=128,
        period_count=2,
        jitter_ps=0.18,
        dbfs=124.2,
        true_peak_db=-0.32,
        headroom_db=18.0,
        playback_state="play",
        camelot_key="10A",
    )

    # First snapshot: initializes baseline, no delta events
    events1 = monitor.process_snapshot(s1)
    assert events1 == []

    # Second snapshot: track transition, camelot change, and sample rate lock change
    s2 = TelemetrySnapshot(
        xruns=1,
        bit_perfect_locked=True,
        sample_rate_hz=192000,
        bit_depth=24,
        alsa_device="hw:0,0",
        dsp_profile="pure-bitperfect",
        spatial_enabled=False,
        current_track_id=2,
        current_track_title="Deep Horizon",
        current_track_artist="Acoustic",
        service_healthy=True,
        buffer_frames=256,
        period_count=2,
        jitter_ps=0.12,
        dbfs=124.2,
        true_peak_db=-0.10,
        headroom_db=12.0,
        playback_state="play",
        camelot_key="11A",
    )

    events2 = monitor.process_snapshot(s2)
    event_names = [e[0] for e in events2]
    assert "track_transition" in event_names
    assert "xrun_detected" in event_names
    assert "dac_lock_changed" in event_names
    assert "telemetry_tick" in event_names

    # Check track transition payload includes camelot_key
    tt_data = next(d for name, d in events2 if name == "track_transition")
    assert tt_data["track_id"] == 2
    assert tt_data["camelot_key"] == "11A"

    # Check dac_lock_changed payload
    dac_data = next(d for name, d in events2 if name == "dac_lock_changed")
    assert dac_data["sample_rate_hz"] == 192000

    # Check formatted SSE event string
    sse_text = format_sse_event("telemetry_tick", tt_data)
    assert sse_text.startswith("event: telemetry_tick\ndata: ")
    assert sse_text.endswith("\n\n")


def test_api_desktop_telemetry_stream_audiophile_metrics(isolated_telemetry_env) -> None:
    """Verify /api/desktop/telemetry/stream returns extended audiophile telemetry and key lookup."""
    db_path, settings_path, music_dir, cfg = isolated_telemetry_env
    track_path = (music_dir / "track1.flac").resolve()
    track_path.write_bytes(b"fLaC")

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tracks (id, path, mtime, size, hash, title, artist, album, genre, duration, status)
            VALUES (42, ?, 1700000000.0, 4096, 'hash_42', 'Solaris', 'Solar Ensemble', 'Galaxies', 'Ambient', 240.0, 'active')
            """,
            (str(track_path),),
        )
        conn.execute(
            """
            INSERT INTO features (track_id, analyzer_version, bpm, key, scale, loudness, danceability, energy, mood_scores, embedding)
            VALUES (42, '1.0.0', 120.0, 'B', 'minor', -12.0, 0.6, 0.7, '{}', ?)
            """,
            (b"\x00" * 512,),
        )
        conn.commit()

    app = create_app(
        db_path=db_path,
        settings=cfg,
    )
    client = TestClient(app)

    with patch(
        "vibeplay.web.get_playback_status",
        return_value={
            "state": "play",
            "track_id": 42,
            "title": "Solaris",
            "artist": "Solar Ensemble",
            "sample_rate": "96000 Hz",
            "bit_depth": "24-bit",
            "daemon_online": True,
        },
    ):
        res = client.get("/api/desktop/telemetry/stream")
        assert res.status_code == 200
        assert "text/event-stream" in res.headers["content-type"]
        assert "event: telemetry_snapshot" in res.text

        # Parse snapshot event JSON data
        lines = res.text.strip().split("\n")
        data_line = next(line for line in lines if line.startswith("data: "))
        data = json.loads(data_line[len("data: ") :])

        assert data["sample_rate_hz"] == 96000
        assert data["bit_depth"] == 24
        assert data["playback_state"] == "play"
        assert data["buffer_frames"] == 128
        assert data["jitter_ps"] == 0.18
        assert data["camelot_key"] == "10A"  # B minor translates to Camelot 10A


def test_telemetry_dom_elements_and_client_scripts(isolated_telemetry_env) -> None:
    """Verify index.html and desktop_scripts.html contain required visualizer hooks."""
    db_path, settings_path, _, cfg = isolated_telemetry_env
    app = create_app(
        db_path=db_path,
        settings=cfg,
    )
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # Micro-visualizer IDs
    assert 'id="telemetry-sample-rate"' in html
    assert 'id="telemetry-jitter"' in html
    assert 'id="telemetry-oscilloscope-path"' in html
    assert 'id="telemetry-oscilloscope-ghost"' in html
    assert 'id="telemetry-dbfs"' in html
    assert 'id="telemetry-true-peak"' in html
    assert 'id="telemetry-meter-track"' in html
    assert 'id="telemetry-camelot-metric"' in html
    assert 'id="telemetry-camelot-center"' in html
    assert 'id="telemetry-harmonic-chips"' in html
    assert 'id="footnote-dma-status"' in html

    # Client-side JavaScript hooks
    assert "initTelemetryStream" in html
    assert "updateTelemetryUi" in html
    assert "updateHeadroomMeter" in html
    assert "renderOscilloscopeFrame" in html
    assert "updateCamelotUi" in html
