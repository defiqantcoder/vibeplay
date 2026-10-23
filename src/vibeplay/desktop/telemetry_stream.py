import json
from dataclasses import dataclass
from typing import Any


@dataclass
class TelemetrySnapshot:
    xruns: int
    bit_perfect_locked: bool
    sample_rate_hz: int
    bit_depth: int
    alsa_device: str
    dsp_profile: str
    spatial_enabled: bool
    current_track_id: int | None
    current_track_title: str | None
    current_track_artist: str | None
    service_healthy: bool


class TelemetryMonitor:
    def __init__(self) -> None:
        self._last_snapshot: TelemetrySnapshot | None = None

    def process_snapshot(self, current: TelemetrySnapshot) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        last = self._last_snapshot

        if last is None:
            self._last_snapshot = current
            return events

        # Track transition
        if current.current_track_id != last.current_track_id:
            events.append((
                "track_transition",
                {
                    "track_id": current.current_track_id,
                    "title": current.current_track_title,
                    "artist": current.current_track_artist,
                }
            ))

        # XRUN detected
        if current.xruns > last.xruns:
            events.append((
                "xrun_detected",
                {
                    "count": current.xruns - last.xruns,
                    "total": current.xruns,
                }
            ))

        # DAC lock changed
        if (current.bit_perfect_locked != last.bit_perfect_locked or
                current.sample_rate_hz != last.sample_rate_hz or
                current.bit_depth != last.bit_depth):
            events.append((
                "dac_lock_changed",
                {
                    "bit_perfect_locked": current.bit_perfect_locked,
                    "sample_rate_hz": current.sample_rate_hz,
                    "bit_depth": current.bit_depth,
                }
            ))

        self._last_snapshot = current
        return events


def format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
