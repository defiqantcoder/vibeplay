import logging
from typing import Any

logger = logging.getLogger(__name__)

def _maybe_notify_track_transition(app, playback: dict[str, Any]) -> None:
    """Dispatch a native desktop track transition notification if enabled and available."""
    track_id = playback.get("track_id") or playback.get("song_id") or playback.get("file")
    if not track_id:
        return
    try:
        from vibeplay.desktop.notifications import TrackNotificationDispatcher

        if not hasattr(app.state, "notification_dispatcher"):
            app.state.notification_dispatcher = TrackNotificationDispatcher()
        dispatcher = app.state.notification_dispatcher
        title = str(playback.get("title") or "Unknown Title")
        artist = str(playback.get("artist") or "Unknown Artist")
        album = str(playback.get("album") or "")
        sample_rate = str(playback.get("sample_rate") or "")
        bit_depth = str(playback.get("bit_depth") or "")
        track_id_val = int(track_id) if (isinstance(track_id, int) or (isinstance(track_id, str) and track_id.isdigit())) else str(track_id)
        if hasattr(dispatcher, "notify_track_change"):
            dispatcher.notify_track_change(
                track_id=track_id_val,
                title=title,
                artist=artist,
                album=album,
                sample_rate=sample_rate,
                bit_depth=bit_depth,
            )
        elif hasattr(dispatcher, "notify"):
            dispatcher.notify(title=title, artist=artist, album=album)
    except Exception as err:
        logger.debug("Desktop track notification skipped: %s", err)
