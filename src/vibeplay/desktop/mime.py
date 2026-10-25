"""MIME type associations, file/URI parsing, and single-instance IPC forwarding for Ubuntu desktop."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from vibeplay.desktop.security import validate_loopback_host

logger = logging.getLogger(__name__)

DEFAULT_IPC_STATE_PATH = Path("~/.config/vibeplay/desktop_ipc.json").expanduser()


def write_ipc_state(
    host: str,
    port: int,
    token: str | None,
    state_path: Path | None = None,
) -> Path:
    """Persist active loopback IPC endpoint and session token atomically with 0o600 permissions."""
    target = (state_path or DEFAULT_IPC_STATE_PATH).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_host = validate_loopback_host(host)
    payload = {
        "host": safe_host,
        "port": int(port),
        "token": token,
        "pid": os.getpid(),
    }
    fd, tmp_name = tempfile.mkstemp(
        prefix=".desktop_ipc_",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp_path, target)
        os.chmod(target, 0o600)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return target


def read_ipc_state(state_path: Path | None = None) -> dict[str, Any] | None:
    """Read active loopback IPC state if present and valid."""
    target = (state_path or DEFAULT_IPC_STATE_PATH).expanduser().resolve()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return None


def clear_ipc_state(state_path: Path | None = None) -> None:
    """Remove the runtime IPC state file on clean supervisor shutdown."""
    target = (state_path or DEFAULT_IPC_STATE_PATH).expanduser().resolve()
    try:
        target.unlink(missing_ok=True)
    except Exception:
        pass


SUPPORTED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".flac",
        ".mp3",
        ".ogg",
        ".wav",
        ".m4a",
        ".aac",
        ".ape",
        ".wv",
        ".opus",
        ".aiff",
    }
)

SUPPORTED_PLAYLIST_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".m3u",
        ".m3u8",
    }
)

MIME_TYPE_ASSOCIATIONS: tuple[str, ...] = (
    "audio/flac",
    "audio/x-flac",
    "audio/mpeg",
    "audio/mp3",
    "audio/ogg",
    "audio/x-vorbis+ogg",
    "audio/opus",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/x-m4a",
    "audio/aac",
    "audio/x-ape",
    "audio/x-wavpack",
    "audio/x-mpegurl",
    "audio/mpegurl",
    "application/vnd.apple.mpegurl",
)


@dataclass(frozen=True)
class MimeOpenTarget:
    """Represents a classified file, playlist, or directory passed via desktop launcher."""

    raw_uri: str
    path: Path
    target_type: str  # "audio" | "playlist" | "directory" | "unsupported"
    exists: bool


def parse_desktop_uri(raw: str) -> Path:
    """Convert a desktop launcher argument (file path or file:// URI) into a local Path.

    Args:
        raw: Local file path or file:// URI passed from XDG desktop Exec=%U.

    Returns:
        Path: Expanded and resolved local filesystem path.

    Raises:
        ValueError: If raw string is empty or uses a non-local URI scheme.
    """
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("Desktop URI or file path cannot be empty.")

    if "://" in cleaned:
        parsed = urlparse(cleaned)
        if parsed.scheme.lower() != "file":
            raise ValueError(f"Unsupported URI scheme '{parsed.scheme}': only local 'file://' URIs are allowed.")
        if parsed.netloc and parsed.netloc.lower() not in ("", "localhost"):
            raise ValueError(f"Remote file URI host '{parsed.netloc}' is not allowed.")
        decoded_path = unquote(parsed.path)
        return Path(decoded_path).expanduser().resolve()

    return Path(cleaned).expanduser().resolve()


def classify_mime_target(raw: str | Path) -> MimeOpenTarget:
    """Classify a file path or file:// URI into audio, playlist, directory, or unsupported."""
    raw_str = str(raw)
    path = parse_desktop_uri(raw_str) if isinstance(raw, str) else raw.expanduser().resolve()
    exists = path.exists()

    if exists and path.is_dir():
        target_type = "directory"
    else:
        ext = path.suffix.lower()
        if ext in SUPPORTED_AUDIO_EXTENSIONS:
            target_type = "audio"
        elif ext in SUPPORTED_PLAYLIST_EXTENSIONS:
            target_type = "playlist"
        else:
            target_type = "unsupported"

    return MimeOpenTarget(
        raw_uri=raw_str,
        path=path,
        target_type=target_type,
        exists=exists,
    )


def parse_m3u_playlist(playlist_path: Path) -> list[Path]:
    """Parse an .m3u or .m3u8 playlist file into resolved local track paths.

    Ignores blank lines, #EXTM3U/#EXTINF comment directives, and non-local URLs.
    Relative paths are resolved relative to the playlist's parent directory.
    """
    resolved_playlist = playlist_path.expanduser().resolve()
    if not resolved_playlist.is_file():
        return []

    base_dir = resolved_playlist.parent
    tracks: list[Path] = []
    content = resolved_playlist.read_text(encoding="utf-8", errors="replace")

    for line in content.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if "://" in entry:
            try:
                track_path = parse_desktop_uri(entry)
            except ValueError:
                continue
        else:
            candidate = Path(entry).expanduser()
            track_path = candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()
        tracks.append(track_path)

    return tracks


def forward_uris_to_running_instance(
    uris: list[str],
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    timeout: float = 1.5,
    ipc_state_path: Path | None = None,
) -> bool:
    """Forward file/URI arguments to an already-running local VibePlay instance.

    Enforces loopback host validation before opening any HTTP connection.

    Returns:
        bool: True if the running instance accepted the payload, False if unreachable.
    """
    if not uris:
        return False

    safe_host = validate_loopback_host(host)
    effective_port = port
    effective_token = token

    if effective_token is None:
        ipc_state = read_ipc_state(ipc_state_path)
        if ipc_state:
            state_token = ipc_state.get("token")
            if isinstance(state_token, str) and state_token:
                effective_token = state_token
            state_port = ipc_state.get("port")
            if isinstance(state_port, int) and port == 8765:
                effective_port = state_port

    url_host = f"[{safe_host}]" if ":" in safe_host else safe_host
    url = f"http://{url_host}:{effective_port}/api/desktop/open"
    body = json.dumps({"uris": list(uris)}).encode("utf-8")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if effective_token:
        headers["X-API-Key"] = effective_token

    req = UrlRequest(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return int(resp.status) == 200
    except (URLError, OSError, ValueError) as err:
        logger.debug(
            "No running instance responded on %s:%d (%s)",
            safe_host,
            effective_port,
            err,
        )
        return False
