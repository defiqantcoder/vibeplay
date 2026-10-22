"""Bit-perfect playback queue integration wrapping python-mpd2 (Music Player Daemon)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

try:
    from mpd import ConnectionError as MPDConnectionError, MPDClient, MPDError
except ImportError:  # pragma: no cover
    MPDClient = Any  # type: ignore
    MPDError = Exception  # type: ignore
    MPDConnectionError = Exception  # type: ignore

from vibeplay.config import Settings, get_settings
from vibeplay.db import get_connection, get_playlist, get_playlist_tracks
from vibeplay.playlist import generate_playlist

logger = logging.getLogger(__name__)


class PlaybackError(Exception):
    """Raised when playback daemon connection or command fails."""

    pass


class MPDTransport:
    """Manages communication and bit-perfect playback queue control with a local MPD daemon."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6600,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.client: MPDClient | None = None

    def connect(self) -> None:
        """Establish connection to MPD daemon via UNIX domain socket or TCP."""
        try:
            client = MPDClient()
            client.timeout = self.timeout
            client.idletimeout = self.timeout

            # UNIX socket path detection
            if self.host.startswith("/") or self.host.startswith("~"):
                socket_path = str(Path(self.host).expanduser())
                logger.debug("Connecting to MPD via UNIX domain socket: %s", socket_path)
                client.connect(socket_path)
            else:
                logger.debug("Connecting to MPD via TCP: %s:%d", self.host, self.port)
                client.connect(self.host, self.port)

            self.client = client
            logger.info("Connected to Music Player Daemon at %s", self.host)
        except Exception as err:
            self.client = None
            msg = f"Could not connect to Music Player Daemon at {self.host}:{self.port} - {err}"
            logger.warning(msg)
            raise PlaybackError(msg) from err

    def disconnect(self) -> None:
        """Safely close connection to MPD."""
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def clear(self) -> None:
        """Clear the current MPD playback queue."""
        if not self.client:
            raise PlaybackError("Not connected to MPD daemon")
        try:
            self.client.clear()
            logger.debug("Cleared MPD queue")
        except Exception as err:
            raise PlaybackError(f"Failed to clear MPD queue: {err}") from err

    def add(self, uri_or_path: str) -> None:
        """Add a single file path or URI to the MPD queue."""
        if not self.client:
            raise PlaybackError("Not connected to MPD daemon")
        try:
            self.client.add(uri_or_path)
        except Exception as err:
            # Fall back to file:// URI if direct path fails
            if not uri_or_path.startswith("file://") and Path(uri_or_path).is_absolute():
                file_uri = Path(uri_or_path).as_uri()
                try:
                    self.client.add(file_uri)
                    return
                except Exception:
                    pass
            raise PlaybackError(f"Failed to add '{uri_or_path}' to MPD queue: {err}") from err

    def add_tracks(self, paths: list[str]) -> int:
        """Queue multiple track paths in order."""
        added_count = 0
        for p in paths:
            try:
                self.add(p)
                added_count += 1
            except Exception as err:
                logger.warning("Could not add track to MPD queue: %s (%s)", p, err)
        return added_count

    def play(self, song_pos: int = 0) -> None:
        """Start playback at specified queue position (0-indexed)."""
        if not self.client:
            raise PlaybackError("Not connected to MPD daemon")
        try:
            self.client.play(song_pos)
            logger.debug("Started MPD playback at song position %d", song_pos)
        except Exception as err:
            raise PlaybackError(f"Failed to start MPD playback: {err}") from err

    def status(self) -> dict[str, Any]:
        """Fetch current MPD daemon playback status."""
        if not self.client:
            raise PlaybackError("Not connected to MPD daemon")
        try:
            return self.client.status()
        except Exception as err:
            raise PlaybackError(f"Failed to fetch MPD status: {err}") from err

    def current_song(self) -> dict[str, Any]:
        """Fetch currently active song details in MPD."""
        if not self.client:
            raise PlaybackError("Not connected to MPD daemon")
        try:
            return self.client.currentsong()
        except Exception as err:
            raise PlaybackError(f"Failed to fetch current song: {err}") from err


@contextmanager
def get_mpd_transport(settings: Settings | None = None) -> Generator[MPDTransport, None, None]:
    """Context manager for acquiring a connected MPDTransport."""
    cfg = settings or get_settings()
    transport = MPDTransport(
        host=cfg.mpd_host,
        port=cfg.mpd_port,
        timeout=cfg.mpd_timeout,
    )
    transport.connect()
    try:
        yield transport
    finally:
        transport.disconnect()


def play_playlist(
    db_path: Path,
    playlist_id: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Load a playlist by ID from SQLite, clear queue, and initiate playback in MPD.

    Args:
        db_path: Path to SQLite database.
        playlist_id: Database ID of the playlist to play.
        settings: Application settings.

    Returns:
        dict[str, Any]: Playback status details.

    Raises:
        ValueError: If playlist not found or empty.
        PlaybackError: If MPD connection or playback commands fail.
    """
    cfg = settings or get_settings()

    with get_connection(db_path) as conn:
        playlist_row = get_playlist(conn, playlist_id)
        if not playlist_row:
            raise ValueError(f"Playlist with ID {playlist_id} not found in database.")
        tracks = get_playlist_tracks(conn, playlist_id)

    if not tracks:
        raise ValueError(f"Playlist {playlist_id} has no tracks to play.")

    track_paths = [t["path"] for t in tracks]

    with get_mpd_transport(cfg) as mpd_client:
        mpd_client.clear()
        added_count = mpd_client.add_tracks(track_paths)
        if added_count > 0:
            mpd_client.play(0)
        status = mpd_client.status()

    return {
        "playlist_id": playlist_id,
        "playlist_name": playlist_row["name"],
        "queued_tracks": added_count,
        "total_tracks": len(tracks),
        "status": status,
        "first_track": {
            "title": tracks[0]["title"],
            "artist": tracks[0]["artist"],
            "path": tracks[0]["path"],
        },
    }


def play_seed(
    db_path: Path,
    seed_track_id: int,
    limit: int = 25,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Generate a cohesive playlist from a seed track and immediately queue into MPD.

    Args:
        db_path: Path to SQLite database.
        seed_track_id: Starting track ID.
        limit: Target track count.
        settings: Application settings.

    Returns:
        dict[str, Any]: Playback and playlist generation summary.
    """
    cfg = settings or get_settings()

    gen_playlist = generate_playlist(
        db_path=db_path,
        name=f"Vibe Seed - Track #{seed_track_id}",
        seed_track_id=seed_track_id,
        limit=limit,
        settings=cfg,
    )

    result = play_playlist(db_path, gen_playlist.playlist_id, settings=cfg)
    result["generated_playlist"] = gen_playlist
    return result
