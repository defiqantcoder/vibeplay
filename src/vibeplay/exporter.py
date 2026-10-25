"""Playlist export module supporting M3U, M3U8, JSON, and CSV formats."""

from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any

from vibeplay.db import get_connection, get_playlist, get_playlist_tracks

logger = logging.getLogger(__name__)


def export_playlist_to_file(
    db_path: Path,
    playlist_id: int,
    output_path: Path,
    export_format: str = "m3u8",
    relative: bool = False,
) -> Path:
    """Export a saved playlist from the database to an external file.

    Args:
        db_path: Path to the SQLite database.
        playlist_id: ID of the playlist to export.
        output_path: Destination file path.
        export_format: Output format ('m3u', 'm3u8', 'json', or 'csv').
        relative: Whether to write track paths relative to output file directory.

    Returns:
        Path: Path to the exported playlist file.

    Raises:
        ValueError: If playlist_id does not exist in database or unsupported format.
    """
    resolved_output = output_path.expanduser().resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    fmt = export_format.lower().strip().lstrip(".")

    with get_connection(db_path) as conn:
        playlist_row = get_playlist(conn, playlist_id)
        if not playlist_row:
            raise ValueError(f"Playlist with ID {playlist_id} not found in database.")

        tracks = get_playlist_tracks(conn, playlist_id)

    logger.info(
        "Exporting playlist %d ('%s', %d tracks) to %s (format=%s, relative=%s)",
        playlist_id,
        playlist_row["name"],
        len(tracks),
        resolved_output,
        fmt,
        relative,
    )

    if fmt in ("m3u", "m3u8"):
        _export_m3u(tracks, resolved_output, relative=relative)
    elif fmt == "json":
        _export_json(playlist_row, tracks, resolved_output, relative=relative)
    elif fmt == "csv":
        _export_csv(tracks, resolved_output, relative=relative)
    else:
        raise ValueError(f"Unsupported playlist export format: '{export_format}'. Supported: m3u, m3u8, json, csv.")

    return resolved_output


def _resolve_track_path(raw_path: str, target_dir: Path, relative: bool) -> str:
    """Resolve an audio track file path as either absolute or relative."""
    track_path = Path(raw_path).expanduser().resolve()
    if relative:
        try:
            return os.path.relpath(track_path, target_dir)
        except ValueError:
            # Fall back to absolute path if drives differ on Windows
            return str(track_path)
    return str(track_path)


def _export_m3u(
    tracks: list[Any],
    output_path: Path,
    relative: bool,
) -> None:
    """Write an extended M3U / M3U8 playlist with UTF-8 encoding."""
    target_dir = output_path.parent
    lines = ["#EXTM3U\n"]

    for t in tracks:
        duration_sec = int(round(float(t["duration"]))) if t["duration"] is not None else -1
        artist = t["artist"] or "Unknown Artist"
        title = t["title"] or "Unknown Title"
        lines.append(f"#EXTINF:{duration_sec},{artist} - {title}\n")
        track_ref = _resolve_track_path(t["path"], target_dir, relative)
        lines.append(f"{track_ref}\n")

    output_path.write_text("".join(lines), encoding="utf-8")


def _export_json(
    playlist_row: Any,
    tracks: list[Any],
    output_path: Path,
    relative: bool,
) -> None:
    """Export playlist metadata and tracks in structured JSON format."""
    target_dir = output_path.parent
    rules = None
    if playlist_row["rules_json"]:
        try:
            rules = json.loads(playlist_row["rules_json"])
        except Exception:
            rules = playlist_row["rules_json"]

    track_list = []
    for t in tracks:
        track_list.append(
            {
                "position": t["position"],
                "track_id": t["track_id"],
                "path": _resolve_track_path(t["path"], target_dir, relative),
                "duration": t["duration"],
                "title": t["title"],
                "artist": t["artist"],
                "album_artist": t["album_artist"],
                "album": t["album"],
                "genre": t["genre"],
                "year": t["year"],
                "mb_recording_id": t["mb_recording_id"],
                "bpm": t["bpm"],
                "key": t["key"],
                "scale": t["scale"],
                "energy": t["energy"],
                "danceability": t["danceability"],
                "loudness": t["loudness"],
            }
        )

    data = {
        "id": playlist_row["id"],
        "name": playlist_row["name"],
        "description": playlist_row["description"],
        "rules": rules,
        "created_at": playlist_row["created_at"],
        "track_count": len(tracks),
        "tracks": track_list,
    }

    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _export_csv(
    tracks: list[Any],
    output_path: Path,
    relative: bool,
) -> None:
    """Export ordered playlist tracks to CSV format."""
    target_dir = output_path.parent
    fieldnames = [
        "position",
        "track_id",
        "title",
        "artist",
        "album_artist",
        "album",
        "genre",
        "year",
        "duration",
        "bpm",
        "key",
        "scale",
        "energy",
        "danceability",
        "loudness",
        "path",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in tracks:
            writer.writerow(
                {
                    "position": t["position"],
                    "track_id": t["track_id"],
                    "title": t["title"] or "",
                    "artist": t["artist"] or "",
                    "album_artist": t["album_artist"] or "",
                    "album": t["album"] or "",
                    "genre": t["genre"] or "",
                    "year": t["year"] if t["year"] is not None else "",
                    "duration": round(float(t["duration"]), 2) if t["duration"] is not None else "",
                    "bpm": round(float(t["bpm"]), 2) if t["bpm"] is not None else "",
                    "key": t["key"] or "",
                    "scale": t["scale"] or "",
                    "energy": round(float(t["energy"]), 3) if t["energy"] is not None else "",
                    "danceability": round(float(t["danceability"]), 3) if t["danceability"] is not None else "",
                    "loudness": round(float(t["loudness"]), 2) if t["loudness"] is not None else "",
                    "path": _resolve_track_path(t["path"], target_dir, relative),
                }
            )
