import json

from vibeplay.desktop.telemetry_stream import TelemetryMonitor, TelemetrySnapshot, format_sse_event


def get_base_snapshot():
    return TelemetrySnapshot(
        xruns=0,
        bit_perfect_locked=True,
        sample_rate_hz=44100,
        bit_depth=16,
        alsa_device="default",
        dsp_profile="none",
        spatial_enabled=False,
        current_track_id=1,
        current_track_title="Track 1",
        current_track_artist="Artist 1",
        service_healthy=True,
    )

def test_telemetry_monitor_initial_snapshot():
    monitor = TelemetryMonitor()
    snap = get_base_snapshot()
    events = monitor.process_snapshot(snap)
    assert events == []
    assert monitor._last_snapshot == snap

def test_track_transition():
    monitor = TelemetryMonitor()
    snap1 = get_base_snapshot()
    monitor.process_snapshot(snap1)

    snap2 = get_base_snapshot()
    snap2.current_track_id = 2
    snap2.current_track_title = "Track 2"
    snap2.current_track_artist = "Artist 2"

    events = monitor.process_snapshot(snap2)
    assert len(events) == 1
    assert events[0][0] == "track_transition"
    assert events[0][1] == {
        "track_id": 2,
        "title": "Track 2",
        "artist": "Artist 2",
    }

def test_xrun_detected():
    monitor = TelemetryMonitor()
    snap1 = get_base_snapshot()
    monitor.process_snapshot(snap1)

    snap2 = get_base_snapshot()
    snap2.xruns = 3

    events = monitor.process_snapshot(snap2)
    assert len(events) == 1
    assert events[0][0] == "xrun_detected"
    assert events[0][1] == {
        "count": 3,
        "total": 3,
    }

def test_dac_lock_changed_bit_perfect():
    monitor = TelemetryMonitor()
    snap1 = get_base_snapshot()
    monitor.process_snapshot(snap1)

    snap2 = get_base_snapshot()
    snap2.bit_perfect_locked = False

    events = monitor.process_snapshot(snap2)
    assert len(events) == 1
    assert events[0][0] == "dac_lock_changed"
    assert events[0][1] == {
        "bit_perfect_locked": False,
        "sample_rate_hz": 44100,
        "bit_depth": 16,
    }

def test_dac_lock_changed_sample_rate():
    monitor = TelemetryMonitor()
    snap1 = get_base_snapshot()
    monitor.process_snapshot(snap1)

    snap2 = get_base_snapshot()
    snap2.sample_rate_hz = 48000

    events = monitor.process_snapshot(snap2)
    assert len(events) == 1
    assert events[0][0] == "dac_lock_changed"
    assert events[0][1] == {
        "bit_perfect_locked": True,
        "sample_rate_hz": 48000,
        "bit_depth": 16,
    }

def test_dac_lock_changed_bit_depth():
    monitor = TelemetryMonitor()
    snap1 = get_base_snapshot()
    monitor.process_snapshot(snap1)

    snap2 = get_base_snapshot()
    snap2.bit_depth = 24

    events = monitor.process_snapshot(snap2)
    assert len(events) == 1
    assert events[0][0] == "dac_lock_changed"
    assert events[0][1] == {
        "bit_perfect_locked": True,
        "sample_rate_hz": 44100,
        "bit_depth": 24,
    }

def test_multiple_events():
    monitor = TelemetryMonitor()
    snap1 = get_base_snapshot()
    monitor.process_snapshot(snap1)

    snap2 = get_base_snapshot()
    snap2.current_track_id = 2
    snap2.xruns = 1

    events = monitor.process_snapshot(snap2)
    assert len(events) == 2
    event_types = [e[0] for e in events]
    assert "track_transition" in event_types
    assert "xrun_detected" in event_types

def test_format_sse_event():
    data = {"track_id": 1, "title": "Test Title"}
    sse = format_sse_event("track_transition", data)
    assert sse == f"event: track_transition\ndata: {json.dumps(data)}\n\n"
