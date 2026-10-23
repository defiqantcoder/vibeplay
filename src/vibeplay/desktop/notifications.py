import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class TrackNotificationDispatcher:
    def __init__(self) -> None:
        self.last_track_id: Optional[str] = None
        self.last_track_path: Optional[str] = None

    def notify_transition(
        self, track_title: str, artist: str, album: str, format_badge: str, track_id: Optional[str] = None, track_path: Optional[str] = None
    ) -> None:
        if track_id is not None and track_id == self.last_track_id:
            return
        if track_path is not None and track_path == self.last_track_path:
            return

        self.last_track_id = track_id
        self.last_track_path = track_path

        title = track_title or "Unknown Title"
        body = f"{artist or 'Unknown Artist'} — {album or 'Unknown Album'} [{format_badge}]"

        notify_bin = shutil.which("notify-send")
        if notify_bin is None:
            logger.info("notify-send not found; skipping track transition notification: %s - %s", title, body)
            return

        try:
            subprocess.run([notify_bin, "--app-name=VibePlay", "--icon=vibeplay", title, body], shell=False, timeout=5, check=True)
        except Exception as e:
            logger.warning("Failed to send track transition notification: %s", e)
