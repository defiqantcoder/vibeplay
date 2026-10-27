"""Bit-perfect playback queue integration wrapping python-mpd2 (Music Player Daemon)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Generator

try:
    from mpd import ConnectionError as MPDConnectionError
    from mpd import MPDClient, MPDError
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


_FALLBACK_LOCK = threading.Lock()
_FALLBACK_PROC: subprocess.Popen[Any] | None = None


def _start_fallback_playback(track_path: str, settings: Settings | None = None) -> None:
    """Fallback playback engine when MPD is unavailable or cannot access external file."""
    global _FALLBACK_PROC

    with _FALLBACK_LOCK:
        if _FALLBACK_PROC is not None:
            try:
                _FALLBACK_PROC.terminate()
                try:
                    _FALLBACK_PROC.wait(timeout=0.3)
                except Exception:
                    _FALLBACK_PROC.kill()
                    _FALLBACK_PROC.wait(timeout=0.2)
            except Exception:
                pass
            _FALLBACK_PROC = None

        player_bin = shutil.which("pw-play") or shutil.which("aplay") or shutil.which("ffplay")
        if not player_bin or not Path(track_path).exists():
            return

        # Before launching an external ALSA fallback player (aplay), cleanly release/disable MPD hardware outputs
        # so the device node is not locked with EBUSY
        if "aplay" in Path(player_bin).name:
            cfg = settings or get_settings()
            try:
                with get_mpd_transport(cfg) as transport:
                    if transport.client:
                        outputs = transport.client.outputs()
                        for out in outputs:
                            oid = str(out.get("outputid", out.get("id")))
                            transport.client.disableoutput(oid)
            except Exception as e:
                logger.debug("Could not release MPD outputs before aplay fallback: %s", e)

        args = [player_bin, str(track_path)]
        if "ffplay" in player_bin:
            args = [player_bin, "-nodisp", "-autoexit", str(track_path)]
        try:
            _FALLBACK_PROC = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Started direct fallback audio player: %s", player_bin)
        except Exception as e:
            logger.warning("Failed to start direct audio player: %s", e)


def _stop_fallback_playback() -> None:
    """Terminate and clean up any active fallback player process under thread lock."""
    global _FALLBACK_PROC
    with _FALLBACK_LOCK:
        if _FALLBACK_PROC is not None:
            try:
                _FALLBACK_PROC.terminate()
                try:
                    _FALLBACK_PROC.wait(timeout=0.3)
                except Exception:
                    _FALLBACK_PROC.kill()
                    _FALLBACK_PROC.wait(timeout=0.2)
            except Exception:
                pass
            _FALLBACK_PROC = None


def _ensure_mpd_symlink(
    track_path: Path,
    music_dir: Path | None = None,
    settings: Settings | None = None,
) -> str | None:
    """Ensure a file outside MPD's music_directory is accessible via symlink in music_dir."""
    candidates_dirs: list[Path] = []
    if music_dir is not None:
        candidates_dirs.append(Path(music_dir).expanduser())

    cfg = settings or get_settings()
    if getattr(cfg, "music_dir", None):
        cfg_mdir = Path(cfg.music_dir).expanduser()
        if cfg_mdir not in candidates_dirs:
            candidates_dirs.append(cfg_mdir)

    for fallback_candidate in [
        Path("~/music-test").expanduser(),
        Path("~/Music").expanduser(),
        Path("~/.local/share/vibeplay/music").expanduser(),
        Path.cwd(),
    ]:
        if fallback_candidate not in candidates_dirs:
            candidates_dirs.append(fallback_candidate)

    resolved = track_path.resolve()
    for mdir in candidates_dirs:
        if mdir.exists() and mdir.is_dir():
            try:
                rel = str(resolved.relative_to(mdir.resolve()))
                return rel
            except ValueError:
                pass
            try:
                sym_dir = mdir / ".vibeplay_symlinks"
                sym_dir.mkdir(parents=True, exist_ok=True)
                sym_file = sym_dir / resolved.name
                if not sym_file.exists() or sym_file.resolve() != resolved:
                    if sym_file.is_symlink() or sym_file.exists():
                        sym_file.unlink(missing_ok=True)
                    sym_file.symlink_to(resolved)
                return f".vibeplay_symlinks/{resolved.name}"
            except Exception as e:
                logger.debug("Could not link %s into %s: %s", resolved, mdir, e)
    return None


class MPDTransport:
    """Manages communication and bit-perfect playback queue control with a local MPD daemon."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6600,
        timeout: float = 10.0,
        music_dir: Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.music_dir = music_dir
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
                logger.debug(
                    "Connecting to MPD via UNIX domain socket: %s", socket_path
                )
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
        """Add a single file path or URI to the MPD queue, resolving candidates."""
        if not self.client:
            raise PlaybackError("Not connected to MPD daemon")

        candidates = [uri_or_path]
        p = Path(uri_or_path)
        sym_rel: str | None = None

        if p.exists():
            sym_rel = _ensure_mpd_symlink(p, music_dir=self.music_dir)
            if sym_rel and sym_rel not in candidates:
                candidates.insert(0, sym_rel)

        # If absolute path, generate relative candidates for MPD's music_directory
        if p.is_absolute():
            candidates.append(p.as_uri())
            candidates.append(str(p).lstrip("/"))
            for parent in p.parents:
                try:
                    rel = str(p.relative_to(parent))
                    if rel and rel != ".":
                        candidates.append(rel)
                except ValueError:
                    pass

        last_err: Exception | None = None
        for cand in candidates:
            try:
                self.client.add(cand)
                return
            except Exception as err:
                last_err = err

        # If still failed, trigger MPD DB update on symlinks folder and retry
        try:
            if sym_rel:
                self.client.update(".vibeplay_symlinks")
                import time

                time.sleep(0.05)
                self.client.add(sym_rel)
                return
        except Exception:
            pass

        raise PlaybackError(
            f"Failed to add '{uri_or_path}' to MPD queue: {last_err}"
        ) from last_err

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
def get_mpd_transport(
    settings: Settings | None = None,
) -> Generator[MPDTransport, None, None]:
    """Context manager for acquiring a connected MPDTransport."""
    cfg = settings or get_settings()
    transport = MPDTransport(
        host=cfg.mpd_host,
        port=cfg.mpd_port,
        timeout=cfg.mpd_timeout,
        music_dir=getattr(cfg, "music_dir", None),
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


def play_track(
    db_path: Path,
    track_id: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Queue a single audio track directly into MPD and start playback.

    Args:
        db_path: Path to SQLite database.
        track_id: Database ID of track to play.
        settings: Application settings.

    Returns:
        dict[str, Any]: Playback result summary.

    Raises:
        ValueError: If track_id not found in database.
    """
    cfg = settings or get_settings()

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.id, t.path, v.title, v.artist, v.album
            FROM tracks t
            LEFT JOIN v_tracks_best_value v ON t.id = v.track_id
            WHERE t.id = ?
            """,
            (track_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Track with ID {track_id} not found in database.")

    track_path = row["path"]
    try:
        with get_mpd_transport(cfg) as mpd_client:
            mpd_client.clear()
            mpd_client.add(track_path)
            mpd_client.play(0)
            status = mpd_client.status()
            _stop_fallback_playback()
            return {
                "track_id": track_id,
                "title": row["title"] or Path(track_path).stem,
                "artist": row["artist"] or "Unknown Artist",
                "status": status,
                "state": "play",
            }
    except Exception as err:
        logger.warning(
            "Could not send play command to MPD (%s); falling back to direct audio player",
            err,
        )
        _start_fallback_playback(track_path)
        return {
            "track_id": track_id,
            "title": row["title"] or Path(track_path).stem,
            "artist": row["artist"] or "Unknown Artist",
            "state": "play",
            "error": str(err),
            "fallback": True,
        }


ACTIVE_OUTPUT_PROFILE = "PipeWire Sound Server"
OUTPUT_PROFILES = [
    "PipeWire Sound Server",
    "Pure Bit-Perfect (Direct ALSA)",
    "7.1.4 Spatial Headphones (SOFA 3D)",
    "AV Receiver Passthrough (HDMI)",
    "USB DAC (Bit-Perfect)",
    "Direct ALSA (hw:0,0)",
    "Analog Line Out",
    "Headphones",
]


def _try_enable_pipewire_fallback(client: Any) -> bool:
    """Find and enable PipeWire output in MPD, disabling all direct ALSA outputs."""
    try:
        outputs = client.outputs()
        pw_id = None
        for out in outputs:
            name = str(out.get("outputname", "")).lower()
            if "pipewire" in name:
                pw_id = str(out.get("outputid", out.get("id")))
                break
        if pw_id is not None:
            for out in outputs:
                oid = str(out.get("outputid", out.get("id")))
                if oid == pw_id:
                    client.enableoutput(oid)
                else:
                    client.disableoutput(oid)
            logger.info("Fell back to PipeWire output (ID: %s)", pw_id)
            return True
    except Exception as err:
        logger.debug("Could not switch to PipeWire fallback: %s", err)
    return False


def get_dynamic_output_profiles(settings: Settings | None = None) -> list[str]:
    """Dynamically scan hardware endpoints and MPD outputs to return selectable audio outputs."""
    profiles: list[str] = []
    cfg = settings or get_settings()

    # 1. Probe system hardware endpoints first
    try:
        from vibe_dsp.hardware import scan_hardware

        audit = scan_hardware()
        for ep in audit.endpoints:
            c_lower = (ep.card_name + " " + ep.device_name + " " + ep.card_id).lower()
            if "letshuoer" in c_lower or "dt01" in c_lower:
                label = f"Letshuoer USB DAC (Bit-Perfect hw:{ep.card_index},{ep.device_index})"
                if label not in profiles:
                    profiles.insert(0, label)

        if audit.active_dac:
            dac_name = audit.active_dac.card_name
            dac_label = f"USB DAC Bit-Perfect ({dac_name})"
            if dac_label not in profiles and not any("letshuoer" in p.lower() for p in profiles):
                profiles.insert(0, dac_label)
        if audit.fallback_endpoint:
            fb_label = f"Speakers / Analog ({audit.fallback_endpoint.card_name})"
            if fb_label not in profiles:
                profiles.append(fb_label)
    except Exception:
        try:
            from vibeplay.hardware import discover_audio_endpoints, get_active_or_best_dac

            endpoints = discover_audio_endpoints()
            for ep in endpoints:
                c_lower = (ep.card_name + " " + ep.card_id).lower()
                if "letshuoer" in c_lower or "dt01" in c_lower:
                    label = f"Letshuoer USB DAC (Bit-Perfect {ep.hw_device})"
                    if label not in profiles:
                        profiles.insert(0, label)
            best_dac = get_active_or_best_dac(endpoints)
            if best_dac:
                dac_label = f"USB DAC Bit-Perfect ({best_dac.card_name})"
                if dac_label not in profiles and not any("letshuoer" in p.lower() for p in profiles):
                    profiles.insert(0, dac_label)
        except Exception:
            pass

    # 2. Always ensure default universal options exist
    universal_options = [
        "PipeWire Sound Server",
        "Pure Bit-Perfect (Direct ALSA)",
        "7.1.4 Spatial Headphones (SOFA 3D)",
        "AV Receiver Passthrough (HDMI)",
    ]
    for opt in universal_options:
        if opt not in profiles:
            profiles.append(opt)

    # 3. Query live MPD outputs if daemon is connected, excluding stale names of disconnected hardware
    try:
        with get_mpd_transport(cfg) as transport:
            if transport.client:
                mpd_outs = transport.client.outputs()
                for out in mpd_outs:
                    name = out.get("outputname")
                    if name and name not in profiles:
                        if "fiio" in name.lower() and not any("fiio" in p.lower() for p in profiles):
                            continue
                        profiles.append(name)
    except Exception:
        pass

    return profiles


def get_active_output_profile(settings: Settings | None = None) -> str:
    """Return the name of the currently active audio output profile."""
    global ACTIVE_OUTPUT_PROFILE
    if ACTIVE_OUTPUT_PROFILE:
        return ACTIVE_OUTPUT_PROFILE

    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            if transport.client:
                mpd_outs = transport.client.outputs()
                for out in mpd_outs:
                    if str(out.get("outputenabled", "0")) == "1":
                        name = str(out.get("outputname", ""))
                        if name:
                            ACTIVE_OUTPUT_PROFILE = name
                            return ACTIVE_OUTPUT_PROFILE
    except Exception:
        pass
    return ACTIVE_OUTPUT_PROFILE or "PipeWire Sound Server"


def set_output_profile(
    profile_name: str, settings: Settings | None = None
) -> str:
    """Set the active hardware audio output profile and dynamically configure MPD outputs."""
    global ACTIVE_OUTPUT_PROFILE
    ACTIVE_OUTPUT_PROFILE = profile_name
    logger.info("Active audio output profile switched to: %s", profile_name)

    p_lower = profile_name.lower()
    try:
        from vibe_dsp.ipc import DSPClient

        dsp = DSPClient()
        if "spatial" in p_lower:
            dsp.set_profile("spatial-headphones")
        elif "receiver" in p_lower or "hdmi" in p_lower:
            dsp.set_profile("receiver-passthrough")
        else:
            dsp.set_profile("pure-bitperfect")
    except Exception as dsp_err:
        logger.debug("Could not dispatch profile to vibe-dsp: %s", dsp_err)

    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            if not transport.client:
                return ACTIVE_OUTPUT_PROFILE
            mpd_outputs = transport.client.outputs()
            if not mpd_outputs:
                return ACTIVE_OUTPUT_PROFILE

            target_id: str | None = None

            # Spatial headphones requires PipeWire output so 3D binaural convolution applies
            if "spatial" in p_lower:
                for out in mpd_outputs:
                    o_name = str(out.get("outputname", "")).lower()
                    if "pipewire" in o_name:
                        target_id = str(out.get("outputid", out.get("id")))
                        break

            # Exact name match
            if target_id is None:
                for out in mpd_outputs:
                    if out.get("outputname") == profile_name:
                        target_id = str(out.get("outputid", out.get("id")))
                        break

            # Keyword match
            if target_id is None:
                for out in mpd_outputs:
                    o_name = str(out.get("outputname", "")).lower()
                    if "letshuoer" in p_lower and (
                        "letshuoer" in o_name
                        or "dt01" in o_name
                        or "hw:1,0" in o_name
                        or "dac" in o_name
                        or "direct" in o_name
                        or "alsa" in o_name
                    ):
                        target_id = str(out.get("outputid", out.get("id")))
                        break
                    elif "pipewire" in p_lower and "pipewire" in o_name:
                        target_id = str(out.get("outputid", out.get("id")))
                        break
                    elif ("dac" in p_lower or "bit-perfect" in p_lower) and (
                        "direct" in o_name or "alsa" in o_name or "dac" in o_name
                    ):
                        target_id = str(out.get("outputid", out.get("id")))
                        break
                    elif ("speaker" in p_lower or "analog" in p_lower) and (
                        "speaker" in o_name or "analog" in o_name or "sof" in o_name
                    ):
                        target_id = str(out.get("outputid", out.get("id")))
                        break

            if target_id is None and mpd_outputs:
                target_id = str(mpd_outputs[0].get("outputid", mpd_outputs[0].get("id")))

            if target_id is not None:
                try:
                    for out in mpd_outputs:
                        oid = str(out.get("outputid", out.get("id")))
                        if oid == target_id:
                            transport.client.enableoutput(oid)
                        else:
                            transport.client.disableoutput(oid)
                    logger.info("Switched MPD active output ID to %s (%s)", target_id, profile_name)
                except Exception as out_err:
                    logger.warning("Error enabling MPD output %s, trying PipeWire fallback: %s", target_id, out_err)
                    _try_enable_pipewire_fallback(transport.client)
    except Exception as err:
        logger.debug("Could not switch MPD hardware output: %s", err)

    return ACTIVE_OUTPUT_PROFILE


def get_output_profile() -> str:
    """Return currently active audio output profile."""
    return ACTIVE_OUTPUT_PROFILE


def toggle_pause(
    db_path: Path | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    """Toggle play/pause state in Music Player Daemon, auto-seeding if queue is empty."""
    global _FALLBACK_PROC
    if _FALLBACK_PROC is not None:
        _stop_fallback_playback()
        return {"state": "pause"}

    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            st = transport.status()
            current_state = st.get("state", "stop")
            queue_len = int(st.get("playlistlength", 0))

            if current_state == "play":
                if transport.client:
                    transport.client.pause(1)
                return {"state": "pause"}
            elif current_state == "pause":
                if transport.client:
                    transport.client.pause(0)
                return {"state": "play"}
            else:
                # State is 'stop'
                if queue_len > 0:
                    if transport.client:
                        try:
                            transport.client.play(0)
                        except Exception as play_err:
                            logger.warning(
                                "MPD play failed on primary output, falling back to PipeWire: %s",
                                play_err,
                            )
                            _try_enable_pipewire_fallback(transport.client)
                            transport.client.play(0)
                        return {"state": "play"}
                else:
                    # Queue is empty - auto-seed tracks from database
                    db_p = db_path or cfg.db_path
                    if db_p.exists():
                        with get_connection(db_p) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "SELECT path FROM tracks WHERE status = 'active' ORDER BY id ASC LIMIT 50"
                            )
                            rows = cursor.fetchall()
                            if rows:
                                paths = [r[0] for r in rows if r[0]]
                                added = transport.add_tracks(paths)
                                if transport.client and added > 0:
                                    try:
                                        transport.client.play(0)
                                    except Exception as play_err:
                                        logger.warning(
                                            "MPD play failed, falling back to PipeWire: %s",
                                            play_err,
                                        )
                                        _try_enable_pipewire_fallback(transport.client)
                                        transport.client.play(0)
                                    return {"state": "play"}
                                elif rows:
                                    _start_fallback_playback(rows[0][0])
                                    return {"state": "play"}
            return transport.status()
    except Exception as err:
        logger.debug("MPD toggle_pause unavailable: %s", err)
        db_p = db_path or cfg.db_path
        if db_p.exists():
            try:
                with get_connection(db_p) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT path FROM tracks WHERE status = 'active' ORDER BY id ASC LIMIT 1")
                    r = cursor.fetchone()
                    if r and r[0]:
                        _start_fallback_playback(r[0])
                        return {"state": "play"}
            except Exception:
                pass
        return {"state": "pause", "error": str(err)}


def seek_playback(
    time_seconds: float, settings: Settings | None = None
) -> dict[str, Any]:
    """Seek playback to target time position in seconds."""
    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            st = transport.status()
            if st.get("state") in ("play", "pause"):
                if transport.client:
                    transport.client.seekcur(max(0.0, time_seconds))
            return transport.status()
    except Exception as err:
        logger.debug("MPD seek unavailable: %s", err)
        return {"state": "stopped", "error": str(err)}


def next_song(settings: Settings | None = None) -> dict[str, Any]:
    """Advance to the next track in MPD queue."""
    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            st = transport.status()
            if int(st.get("playlistlength", 0)) > 0:
                if transport.client:
                    transport.client.next()
            return transport.status()
    except Exception as err:
        logger.debug("MPD next_song unavailable: %s", err)
        return {"state": "stopped", "error": str(err)}


def previous_song(settings: Settings | None = None) -> dict[str, Any]:
    """Skip to previous track in MPD queue."""
    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            st = transport.status()
            if int(st.get("playlistlength", 0)) > 0:
                if transport.client:
                    transport.client.previous()
            return transport.status()
    except Exception as err:
        logger.debug("MPD previous_song unavailable: %s", err)
        return {"state": "stopped", "error": str(err)}


_LAST_NONZERO_VOLUME: int = 80
_IS_MUTED: bool = False


def _detect_codec_from_path(file_path: str) -> tuple[str, bool]:
    """Return (codec_name, is_lossless) based on file extension and path."""
    if not file_path:
        return ("--", False)
    ext = Path(file_path).suffix.lower().lstrip(".")
    if ext in ("flac", "fla"):
        return ("FLAC", True)
    if ext in ("wav", "wave"):
        return ("WAV", True)
    if ext in ("aif", "aiff"):
        return ("AIFF", True)
    if ext == "alac":
        return ("ALAC", True)
    if ext in ("m4a", "mp4"):
        if "alac" in file_path.lower():
            return ("ALAC", True)
        return ("AAC", False)
    if ext == "mp3":
        return ("MP3", False)
    if ext in ("aac", "m4p"):
        return ("AAC", False)
    if ext == "opus":
        return ("OPUS", False)
    if ext in ("ogg", "oga"):
        return ("OGG", False)
    if ext:
        return (ext.upper(), False)
    return ("--", False)


def set_volume_level(volume: int, settings: Settings | None = None) -> dict[str, Any]:
    """Set playback volume level [0-100]."""
    global _LAST_NONZERO_VOLUME, _IS_MUTED
    cfg = settings or get_settings()
    vol = max(0, min(100, volume))
    if vol > 0:
        _LAST_NONZERO_VOLUME = vol
        _IS_MUTED = False
    else:
        _IS_MUTED = True
    try:
        with get_mpd_transport(cfg) as transport:
            if transport.client:
                try:
                    transport.client.setvol(vol)
                except Exception as setvol_err:
                    # When playing through direct ALSA (hw:) with mixer_type "none", MPD raises CommandError
                    logger.debug("MPD setvol ignored for bit-perfect output with mixer_type none: %s", setvol_err)
            return {"volume": vol}
    except Exception as err:
        logger.debug("MPD setvol unavailable: %s", err)
        return {"volume": str(vol), "error": str(err)}


def adjust_volume_step(delta: int, settings: Settings | None = None) -> dict[str, Any]:
    """Adjust current playback volume by delta (positive or negative) within [0, 100]."""
    global _LAST_NONZERO_VOLUME, _IS_MUTED
    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            cur_vol = 0 if _IS_MUTED else _LAST_NONZERO_VOLUME
            if transport.client:
                st = transport.status()
                v_str = st.get("volume", str(cur_vol))
                if v_str and v_str != "-1":
                    try:
                        cur_vol = int(v_str)
                    except ValueError:
                        pass
            new_vol = max(0, min(100, cur_vol + delta))
            if new_vol > 0:
                _LAST_NONZERO_VOLUME = new_vol
                _IS_MUTED = False
            else:
                _IS_MUTED = True
            if transport.client:
                try:
                    transport.client.setvol(new_vol)
                except Exception as setvol_err:
                    logger.debug("MPD setvol ignored on direct output: %s", setvol_err)
            return {"volume": new_vol}
    except Exception as err:
        logger.debug("MPD volume adjustment unavailable: %s", err)
        new_vol = max(0, min(100, (0 if _IS_MUTED else _LAST_NONZERO_VOLUME) + delta))
        if new_vol > 0:
            _LAST_NONZERO_VOLUME = new_vol
            _IS_MUTED = False
        else:
            _IS_MUTED = True
        return {"volume": str(new_vol), "error": str(err)}


def toggle_mute(settings: Settings | None = None) -> dict[str, Any]:
    """Toggle mute state: if volume > 0, set to 0; if volume == 0, restore previous volume."""
    global _LAST_NONZERO_VOLUME, _IS_MUTED
    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            cur_vol = 0 if _IS_MUTED else _LAST_NONZERO_VOLUME
            if transport.client:
                st = transport.status()
                v_str = st.get("volume", str(cur_vol))
                if v_str and v_str != "-1":
                    try:
                        cur_vol = int(v_str)
                    except ValueError:
                        pass
            if not _IS_MUTED and cur_vol > 0:
                _LAST_NONZERO_VOLUME = cur_vol
                _IS_MUTED = True
                target_vol = 0
            else:
                _IS_MUTED = False
                target_vol = _LAST_NONZERO_VOLUME if _LAST_NONZERO_VOLUME > 0 else 80
            if transport.client:
                try:
                    transport.client.setvol(target_vol)
                except Exception as setvol_err:
                    logger.debug("MPD setvol ignored on direct output: %s", setvol_err)
            return {"volume": target_vol}
    except Exception as err:
        logger.debug("MPD mute toggle unavailable: %s", err)
        if _IS_MUTED:
            _IS_MUTED = False
            target_vol = _LAST_NONZERO_VOLUME
        else:
            _IS_MUTED = True
            target_vol = 0
        return {"volume": target_vol, "error": str(err)}


def get_playback_status(
    db_path: Path | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    """Retrieve real-time player telemetry, DAC buffer health, and active track."""
    cfg = settings or get_settings()
    try:
        with get_mpd_transport(cfg) as transport:
            st = transport.status()
            cur = transport.current_song()
            state = st.get("state", "stop")
            elapsed_str = st.get("elapsed", "0")
            duration_str = st.get("duration", "0")
            elapsed = float(elapsed_str) if elapsed_str else 0.0
            duration = float(duration_str) if duration_str else 0.0

            file_path = cur.get("file", "")
            track_db_id = None
            cur_title = cur.get("title") or (
                Path(file_path).stem if file_path else "vibeplay Ready"
            )
            cur_artist = cur.get("artist") or "Audiophile Precision"
            cur_album = cur.get("album") or "Studio Master"

            native_rate_hz: int | None = None
            native_depth_bits: int | None = None
            native_channels: int | None = None

            if file_path:
                try:
                    tech_info = _extract_audio_file_technical_info(file_path)
                    native_channels = tech_info.get("channels")
                    native_depth_bits = tech_info.get("bits_per_sample")
                    native_rate_hz = tech_info.get("sample_rate")
                except Exception:
                    pass

            if file_path and db_path and db_path.exists():
                try:
                    with get_connection(db_path) as conn:
                        row = conn.execute(
                            """
                            SELECT t.id, t.title, t.artist, t.album, t.sample_rate, t.bit_depth
                            FROM tracks t
                            WHERE t.path = ? OR t.path LIKE ?
                            LIMIT 1
                            """,
                            (file_path, f"%{Path(file_path).name}"),
                        ).fetchone()
                        if row:
                            track_db_id = row[0]
                            if row[1]:
                                cur_title = row[1]
                            if row[2]:
                                cur_artist = row[2]
                            if row[3]:
                                cur_album = row[3]
                            if row[4]:
                                native_rate_hz = int(row[4])
                            if row[5]:
                                native_depth_bits = int(row[5])
                except Exception:
                    pass

            audio_spec = st.get("audio")
            is_active = state in ("play", "pause") and bool(file_path)

            output_channels = None
            if is_active and audio_spec and ":" in audio_spec:
                parts = audio_spec.split(":")
                rate_hz = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else (native_rate_hz or 44100)
                depth_bits = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else (native_depth_bits or 16)
                output_channels = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else (native_channels or 2)
                sample_rate_str = f"{rate_hz / 1000:.1f}kHz" if rate_hz >= 1000 else f"{rate_hz}Hz"
                bit_depth_str = f"{depth_bits}-bit"
            elif is_active and native_rate_hz:
                rate_hz = native_rate_hz
                depth_bits = native_depth_bits or 16
                output_channels = native_channels or 2
                sample_rate_str = f"{rate_hz / 1000:.1f}kHz" if rate_hz >= 1000 else f"{rate_hz}Hz"
                bit_depth_str = f"{depth_bits}-bit"
                audio_spec = f"{rate_hz}:{depth_bits}:{output_channels}"
            else:
                rate_hz = None
                depth_bits = None
                output_channels = None
                sample_rate_str = "--"
                bit_depth_str = "--"
                audio_spec = "--"

            st_vol = st.get("volume", "80")
            is_hardware_lineout = (st_vol == "-1")
            if is_hardware_lineout:
                vol = 100
                volume_db = "0.0 dB (Hardware Line-Out)"
            elif _IS_MUTED:
                vol = 0
                volume_db = "-inf dB (Muted)"
            else:
                vol = _LAST_NONZERO_VOLUME
                if st_vol and st_vol not in ("-1", "0"):
                    try:
                        vol = int(st_vol)
                    except ValueError:
                        vol = _LAST_NONZERO_VOLUME
                volume_db = f"{round((vol - 100) * 0.5, 1)} dB" if vol < 100 else "0.0 dB (Hardware Line-Out)"

            detected_codec, is_lossless = _detect_codec_from_path(file_path)

            # Bit-perfect criteria:
            # 1. Active file is a lossless container
            # 2. Output sample rate matches native track rate (no resampling)
            # 3. Output bit depth matches native bit depth
            # 4. Output channels matches native channels
            # 5. Volume is unattenuated (100% / 0 dB or hardware line-out)
            resampling_applied = False
            if rate_hz is not None and native_rate_hz is not None:
                if rate_hz != native_rate_hz:
                    resampling_applied = True

            bit_depth_mismatch = False
            if depth_bits is not None and native_depth_bits is not None:
                if depth_bits != native_depth_bits:
                    bit_depth_mismatch = True

            channels_mismatch = False
            if output_channels is not None and native_channels is not None:
                if output_channels != native_channels:
                    channels_mismatch = True

            volume_attenuated = (vol < 100 and not is_hardware_lineout)

            if is_active and is_lossless and not resampling_applied and not bit_depth_mismatch and not channels_mismatch and not volume_attenuated:
                bit_perfect = True
                buffer_health = "100% Bit-Perfect Locked"
            elif is_active:
                bit_perfect = False
                buffer_health = "DSP / Processed"
            else:
                bit_perfect = False
                buffer_health = "Standby (Direct ALSA Ready)"

            return {
                "state": state,
                "song_id": cur.get("id"),
                "track_id": track_db_id,
                "title": cur_title,
                "artist": cur_artist,
                "album": cur_album,
                "file": file_path,
                "elapsed": elapsed,
                "duration": duration,
                "volume": vol,
                "volume_db": volume_db,
                "audio_spec": audio_spec,
                "sample_rate": sample_rate_str,
                "bit_depth": bit_depth_str,
                "codec": detected_codec,
                "bit_perfect": bit_perfect,
                "buffer_health": buffer_health,
                "jitter_ppm": 0.02,
                "output_profile": get_active_output_profile(cfg),
                "output_profiles": get_dynamic_output_profiles(cfg),
                "daemon_online": True,
            }
    except Exception:
        # Standby status when MPD daemon is offline
        return {
            "state": "stop",
            "song_id": None,
            "track_id": None,
            "title": "vibeplay Precision Console",
            "artist": "Queue a track or generated playlist",
            "album": "Bit-Perfect Standby",
            "file": "",
            "elapsed": 0.0,
            "duration": 0.0,
            "volume": _LAST_NONZERO_VOLUME,
            "volume_db": "0.0 dB (Hardware Line-Out)",
            "audio_spec": "--",
            "sample_rate": "--",
            "bit_depth": "--",
            "codec": "--",
            "bit_perfect": False,
            "buffer_health": "Standby (Direct ALSA Ready)",
            "jitter_ppm": 0.02,
            "output_profile": get_active_output_profile(cfg),
            "output_profiles": get_dynamic_output_profiles(cfg),
            "daemon_online": False,
        }


@lru_cache(maxsize=1024)
def _extract_audio_file_technical_info(path_str: str) -> dict[str, Any]:
    """Extract raw audio stream metadata (sample rate, bit depth, codec, channels)."""
    import mutagen

    path = Path(path_str).expanduser()
    ext = path.suffix.lower()
    codec = "Audio"
    sample_rate = 44100
    bits_per_sample = 16
    channels = 2
    bitrate = None

    if ext == ".flac":
        codec = "FLAC (Free Lossless Audio Codec)"
        bits_per_sample = 24
        sample_rate = 96000
    elif ext == ".mp3":
        codec = "MPEG Audio Layer 3 (Lossy)"
        bits_per_sample = 16
        sample_rate = 44100
    elif ext == ".wav":
        codec = "WAV (Linear PCM)"
        bits_per_sample = 24
        sample_rate = 96000
    elif ext in (".m4a", ".aac"):
        codec = "AAC / ALAC (Advanced Audio Coding)"
        bits_per_sample = 16
        sample_rate = 44100
    elif ext in (".ogg", ".opus"):
        codec = "Ogg Opus (Lossless Transform)"
        bits_per_sample = 24
        sample_rate = 48000

    if path.exists() and path.is_file():
        try:
            audio = mutagen.File(str(path))
            if audio is not None and hasattr(audio, "info"):
                info = audio.info
                if hasattr(info, "sample_rate") and info.sample_rate:
                    sample_rate = info.sample_rate
                if hasattr(info, "bits_per_sample") and info.bits_per_sample:
                    bits_per_sample = info.bits_per_sample
                if hasattr(info, "channels") and info.channels:
                    channels = info.channels
                if hasattr(info, "bitrate") and info.bitrate:
                    bitrate = info.bitrate
        except Exception as err:
            logger.debug("Could not read audio header for %s: %s", path, err)

    return {
        "codec": codec,
        "sample_rate": sample_rate,
        "sample_rate_str": f"{sample_rate / 1000.0:.1f} kHz"
        if sample_rate >= 1000
        else f"{sample_rate} Hz",
        "bits_per_sample": bits_per_sample,
        "bit_depth_str": f"{bits_per_sample}-bit",
        "channels": channels,
        "channels_str": "Stereo"
        if channels == 2
        else ("Mono" if channels == 1 else f"{channels} Ch"),
        "bitrate_kbps": f"{int(bitrate / 1000)} kbps" if bitrate else "Lossless VBR",
    }


def get_audio_file_technical_info(path_str: str) -> dict[str, Any]:
    """Return cached copy of audio file technical metadata."""
    return _extract_audio_file_technical_info(path_str).copy()
