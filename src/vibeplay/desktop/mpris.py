"""D-Bus MPRIS2 implementation for VibePlay."""

import json
import logging
import threading
import time
import urllib.error
from typing import Any
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


_NO_TRACK_PATH = "/org/mpris/MediaPlayer2/TrackList/NoTrack"


def _project_song_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Project either nested ``current_song`` or flat status fields into MPRIS metadata.

    For flat status payloads, requires a song/track identifier or a nonempty file
    path so offline standby placeholder text never masquerades as a playing track.
    """
    nested = data.get("current_song")
    if isinstance(nested, dict) and nested:
        song = nested
    elif (
        data.get("id") is not None
        or data.get("song_id") is not None
        or data.get("track_id") is not None
        or bool(str(data.get("file") or "").strip())
    ):
        song = data
    else:
        return {}

    raw_id = song.get("id") if song.get("id") is not None else song.get("song_id")
    if raw_id is None:
        raw_id = song.get("track_id")
    safe_id = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(raw_id if raw_id is not None else 0)) or "0"
    artist = song.get("artist")
    return {
        "mpris:trackid": f"/org/mpris/MediaPlayer2/TrackList/{safe_id}",
        "xesam:title": str(song.get("title") or ""),
        "xesam:artist": [str(artist)] if artist else [],
        "xesam:album": str(song.get("album") or ""),
        "mpris:length": int(float(song.get("duration") or 0) * 1000000),
    }


def _format_mpris_metadata(meta: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    """Encode a metadata mapping as D-Bus ``a{sv}`` typed pairs for Jeepney."""
    if not meta:
        return {"mpris:trackid": ("o", _NO_TRACK_PATH)}
    return {
        "mpris:trackid": ("o", meta.get("mpris:trackid", _NO_TRACK_PATH)),
        "xesam:title": ("s", meta.get("xesam:title", "")),
        "xesam:artist": ("as", meta.get("xesam:artist", [])),
        "xesam:album": ("s", meta.get("xesam:album", "")),
        "mpris:length": ("x", meta.get("mpris:length", 0)),
    }


class MPRISServer:
    """Lightweight pure-python D-Bus server for MPRIS interface."""

    def __init__(self, runner: Any) -> None:
        """Initialize the MPRIS server wrapper for a desktop runner instance."""
        self.runner = runner
        self.is_running = False
        self._dbus_thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None

        self.current_playback_status = "Stopped"
        self.current_metadata: dict[str, Any] = {}
        self.conn = None
        self._jeepney_router = None

    def start(self) -> None:
        """Start background D-Bus listener and telemetry polling threads."""
        self.is_running = True
        self._dbus_thread = threading.Thread(target=self._run_dbus, name="vibeplay-mpris-dbus", daemon=True)
        self._poll_thread = threading.Thread(target=self._run_poll, name="vibeplay-mpris-poll", daemon=True)
        self._dbus_thread.start()
        self._poll_thread.start()

    def stop(self) -> None:
        """Stop MPRIS background loops and close the D-Bus connection."""
        self.is_running = False
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

    def _api_post(self, path: str) -> None:
        """Forward an MPRIS playback command to the local web API."""
        if not self.runner or not getattr(self.runner, "is_running", True):
            return
        url = f"http://{self.runner.host}:{self.runner.port}/api{path}"
        try:
            req = Request(url, method="POST")
            with urlopen(req, timeout=1.0) as _:
                pass
        except Exception as e:
            logger.debug("MPRIS API call %s failed: %s", path, e)

    def _run_dbus(self) -> None:
        """Listen on the session D-Bus for MPRIS Player methods and Properties.Get."""
        try:
            from jeepney import new_method_return
            from jeepney.bus_messages import message_bus
            from jeepney.io.blocking import open_dbus_connection
        except ImportError:
            logger.warning("Jeepney library not installed, MPRIS interface disabled.")
            return

        try:
            self.conn = open_dbus_connection(bus="SESSION")
            msg = message_bus.RequestName("org.mpris.MediaPlayer2.vibeplay")
            self.conn.send_and_get_reply(msg)
            logger.info("MPRIS D-Bus interface successfully attached (jeepney).")

            # Since jeepney is very lightweight, we implement a custom polling loop
            # and just parse incoming messages to satisfy the requirement
            while self.is_running:
                try:
                    msg = self.conn.receive(timeout=0.5)
                    if not msg:
                        continue

                    if msg.header.message_type.name == "method_call":
                        method = msg.header.fields.get(3)  # MEMBER
                        interface = msg.header.fields.get(2)  # INTERFACE

                        if interface == "org.mpris.MediaPlayer2.Player":
                            if method == "Play":
                                self._api_post("/player/toggle")
                                self.conn.send_message(new_method_return(msg, ""))
                            elif method == "Pause":
                                self._api_post("/player/toggle")
                                self.conn.send_message(new_method_return(msg, ""))
                            elif method == "PlayPause":
                                self._api_post("/player/toggle")
                                self.conn.send_message(new_method_return(msg, ""))
                            elif method == "Next":
                                self._api_post("/player/next")
                                self.conn.send_message(new_method_return(msg, ""))
                            elif method == "Previous":
                                self._api_post("/player/prev")
                                self.conn.send_message(new_method_return(msg, ""))
                            elif method == "Stop":
                                self._api_post("/player/transport")
                                self.conn.send_message(new_method_return(msg, ""))
                        elif interface == "org.freedesktop.DBus.Properties" and method == "Get":
                            # Extremely simple property handler
                            prop_iface, prop_name = msg.body
                            if prop_iface == "org.mpris.MediaPlayer2.Player":
                                if prop_name == "PlaybackStatus":
                                    self.conn.send_message(new_method_return(msg, "v", (("s", self.current_playback_status),)))
                                elif prop_name == "Metadata":
                                    formatted_metadata = _format_mpris_metadata(self.current_metadata)
                                    self.conn.send_message(new_method_return(msg, "v", (("a{sv}", formatted_metadata),)))
                except TimeoutError:
                    pass
                except Exception as e:
                    logger.debug("Jeepney message error: %s", e)
            self.conn.close()
        except Exception as e:
            logger.warning("Could not connect to SESSION D-Bus for MPRIS (jeepney): %s", e)

    def _run_poll(self) -> None:
        """Poll telemetry to update PropertiesChanged signal."""
        if not self.runner:
            return

        time.sleep(2.0)  # Wait for backend

        while self.is_running:
            try:
                if not getattr(self.runner, "is_running", True):
                    break
                url = f"http://{self.runner.host}:{self.runner.port}/api/player/status"
                with urlopen(url, timeout=1.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))

                        state = data.get("state", "stop")
                        status = "Playing" if state == "play" else "Paused" if state == "pause" else "Stopped"
                        metadata = _project_song_metadata(data)

                        changed: dict[str, Any] = {}
                        if self.current_playback_status != status:
                            changed["PlaybackStatus"] = status
                            self.current_playback_status = status

                        if self.current_metadata != metadata:
                            changed["Metadata"] = metadata
                            self.current_metadata = metadata

                        if changed and self.conn:
                            try:
                                from jeepney import DBusAddress, new_signal

                                formatted_changed: dict[str, tuple[str, Any]] = {}
                                if "PlaybackStatus" in changed:
                                    formatted_changed["PlaybackStatus"] = ("s", changed["PlaybackStatus"])
                                if "Metadata" in changed:
                                    formatted_changed["Metadata"] = ("a{sv}", _format_mpris_metadata(changed["Metadata"]))

                                # Signal for PropertiesChanged
                                sig = new_signal(
                                    DBusAddress(
                                        "/org/mpris/MediaPlayer2",
                                        bus_name="org.mpris.MediaPlayer2.vibeplay",
                                        interface="org.freedesktop.DBus.Properties"
                                    ),
                                    "PropertiesChanged",
                                    "sa{sv}as",
                                    ("org.mpris.MediaPlayer2.Player", formatted_changed, []),
                                )
                                self.conn.send_message(sig)
                            except Exception as e:
                                logger.debug("Failed to emit PropertiesChanged: %s", e)

            except urllib.error.URLError:
                pass  # Server might not be ready
            except Exception as e:
                logger.debug("MPRIS telemetry polling error: %s", e)

            time.sleep(1.0)
