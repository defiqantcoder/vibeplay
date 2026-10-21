"""Scanner module for traversing local audio libraries and extracting metadata.

Guarantees strict read-only access to audio files. No files will ever be
modified, renamed, moved, retagged, or deleted on disk.
"""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import mutagen
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

from vibeplay.db import (
    get_connection,
    get_existing_tracks,
    init_db,
    insert_track,
    mark_tracks_missing,
    update_track,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset(
    {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"}
)

ProgressCallback = Callable[[int, int, Path], None]


@dataclass(frozen=True)
class ExtractedMetadata:
    """Normalized metadata extracted from an audio file."""

    duration: float | None
    bitrate: int | None
    title: str | None
    artist: str | None
    album_artist: str | None
    album: str | None
    track_no: int | None
    track_total: int | None
    disc_no: int | None
    disc_total: int | None
    year: int | None
    genre: str | None
    has_cover: bool
    tags_json: str


@dataclass
class ScanSummary:
    """Summary of library scan execution."""

    new: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    errors: int = 0

    @property
    def total_processed(self) -> int:
        """Total number of scanned files evaluated."""
        return self.new + self.updated + self.unchanged + self.errors


def is_audio_file(file_path: Path) -> bool:
    """Check if a path points to a supported audio file by extension.

    Args:
        file_path: Filesystem path to evaluate.

    Returns:
        bool: True if extension is supported, False otherwise.
    """
    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS


def compute_file_hash(path: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 hash of a file opened in read-only binary mode.

    Args:
        path: Path to the target file.
        chunk_size: Byte size of chunks read into memory.

    Returns:
        str: Hexadecimal SHA-256 digest string.
    """
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def _parse_first_string(tags: Any, *keys: str) -> str | None:
    """Find and return the first non-empty string value for candidate tag keys.

    Args:
        tags: Mutagen tags dictionary or object.
        *keys: Tag key candidates in priority order.

    Returns:
        str | None: First matched string stripped of whitespace, or None.
    """
    if not tags:
        return None

    for key in keys:
        val = tags.get(key)
        if val is None:
            continue
        if isinstance(val, (list, tuple)) and len(val) > 0:
            first = str(val[0]).strip()
            if first:
                return first
        elif hasattr(val, "text") and len(val.text) > 0:
            first = str(val.text[0]).strip()
            if first:
                return first
        else:
            s = str(val).strip()
            if s:
                return s
    return None


def _parse_int_pair(val: Any) -> tuple[int | None, int | None]:
    """Parse a track or disc tag representation into (number, total) integers.

    Handles formats like: "6/12", "6", 6, [(6, 12)], (6, 12).

    Args:
        val: Raw tag value.

    Returns:
        tuple[int | None, int | None]: Parsed (number, total) pair.
    """
    if val is None:
        return None, None

    if isinstance(val, (list, tuple)) and len(val) > 0:
        val = val[0]

    if isinstance(val, (list, tuple)) and len(val) > 0:
        first = val[0]
        second = val[1] if len(val) > 1 else None
        num = int(first) if (isinstance(first, int) or (isinstance(first, str) and first.isdigit())) else None
        total = (
            int(second)
            if (isinstance(second, int) or (isinstance(second, str) and second.isdigit()))
            else None
        )
        return num, total

    s = str(val).strip()
    match = re.match(r"^(\d+)(?:/(\d+))?$", s)
    if match:
        num = int(match.group(1))
        total = int(match.group(2)) if match.group(2) else None
        return num, total

    return None, None


def _parse_year(val: Any) -> int | None:
    """Extract a 4-digit release year from a tag value.

    Args:
        val: Date or year string or object.

    Returns:
        int | None: 4-digit year integer or None.
    """
    if val is None:
        return None
    s = str(val).strip()
    match = re.search(r"\b(\d{4})\b", s)
    if match:
        return int(match.group(1))
    return None


def _detect_cover_art(audio: Any) -> bool:
    """Determine whether embedded cover artwork exists in the audio container.

    Args:
        audio: Mutagen File object.

    Returns:
        bool: True if embedded cover art is present, False otherwise.
    """
    # FLAC pictures
    if getattr(audio, "pictures", None):
        return bool(audio.pictures)

    tags = getattr(audio, "tags", None)
    if not tags:
        return False

    # ID3 APIC frames
    if any(str(k).startswith("APIC") for k in tags.keys()):
        return True

    # MP4 covr atom
    if "covr" in tags and bool(tags.get("covr")):
        return True

    # Vorbis comment picture blocks
    for key in ("metadata_block_picture", "METADATA_BLOCK_PICTURE"):
        if key in tags and bool(tags.get(key)):
            return True

    return False


def _serialize_tags(tags: Any) -> str:
    """Safely serialize mutagen tag objects to a JSON string.

    Args:
        tags: Mutagen tags container.

    Returns:
        str: Valid JSON dictionary string.
    """
    if not tags:
        return json.dumps({})

    clean_dict: dict[str, Any] = {}
    for k, v in tags.items():
        key_str = str(k)
        if hasattr(v, "text"):
            clean_dict[key_str] = [str(item) for item in v.text]
        elif isinstance(v, (list, tuple)):
            clean_dict[key_str] = [str(item) for item in v]
        elif isinstance(v, (bytes, bytearray)):
            clean_dict[key_str] = f"<binary data: {len(v)} bytes>"
        else:
            clean_dict[key_str] = str(v)

    return json.dumps(clean_dict, ensure_ascii=False)


def extract_metadata(file_path: Path) -> ExtractedMetadata:
    """Read metadata tags and audio stream properties using mutagen.

    Guarantees read-only inspection. Never modifies the source file.

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        ExtractedMetadata: Normalized metadata and serialized tags JSON.

    Raises:
        ValueError: If file is not recognized as a valid audio container.
    """
    # Open file with mutagen in read mode
    audio = mutagen.File(file_path)
    if audio is None:
        raise ValueError(f"Mutagen could not recognize audio format: {file_path}")

    # Audio stream properties
    duration: float | None = None
    if hasattr(audio, "info") and getattr(audio.info, "length", None) is not None:
        duration = float(audio.info.length)

    bitrate: int | None = None
    if hasattr(audio, "info") and getattr(audio.info, "bitrate", None) is not None:
        bitrate = int(audio.info.bitrate)

    tags = getattr(audio, "tags", None)

    # Core tag extraction
    title = _parse_first_string(tags, "title", "TIT2", "\xa9nam")
    artist = _parse_first_string(tags, "artist", "TPE1", "\xa9ART")
    album_artist = _parse_first_string(
        tags, "albumartist", "album_artist", "TPE2", "aART", "ensemble"
    )
    album = _parse_first_string(tags, "album", "TALB", "\xa9alb")
    genre = _parse_first_string(tags, "genre", "TCON", "\xa9gen")

    # Track and disc numbers
    raw_track = None
    if tags:
        for k in ("tracknumber", "track", "TRCK", "trkn"):
            if k in tags:
                raw_track = tags[k]
                break
    track_no, track_total = _parse_int_pair(raw_track)

    raw_disc = None
    if tags:
        for k in ("discnumber", "disc", "TPOS", "disk"):
            if k in tags:
                raw_disc = tags[k]
                break
    disc_no, disc_total = _parse_int_pair(raw_disc)

    # Year
    raw_date = _parse_first_string(tags, "date", "year", "TDRC", "TYER", "\xa9day")
    year = _parse_year(raw_date)

    # Cover art
    has_cover = _detect_cover_art(audio)

    # Serialized tags JSON
    tags_json = _serialize_tags(tags)

    return ExtractedMetadata(
        duration=duration,
        bitrate=bitrate,
        title=title,
        artist=artist,
        album_artist=album_artist,
        album=album,
        track_no=track_no,
        track_total=track_total,
        disc_no=disc_no,
        disc_total=disc_total,
        year=year,
        genre=genre,
        has_cover=has_cover,
        tags_json=tags_json,
    )


def find_audio_files(directory: Path) -> list[Path]:
    """Recursively collect supported audio files within a directory.

    Ignores hidden files and directories (names starting with '.').

    Args:
        directory: Root path to search.

    Returns:
        list[Path]: Sorted list of resolved audio file paths.
    """
    resolved_dir = directory.resolve()
    audio_files: list[Path] = []

    for root, dirs, files in os.walk(resolved_dir, followlinks=False):
        # Exclude hidden directories in-place to avoid descending
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for filename in files:
            if filename.startswith("."):
                continue
            file_path = Path(root) / filename
            if is_audio_file(file_path):
                audio_files.append(file_path.resolve())

    audio_files.sort()
    return audio_files


def scan_directory(
    library_path: Path,
    db_path: Path,
    progress_callback: ProgressCallback | None = None,
) -> ScanSummary:
    """Scan an audio directory and incrementally synchronize tracks into SQLite.

    Guarantees strict read-only access to library files.
    - New files are parsed and inserted.
    - Files with matching path, mtime, and size are skipped as unchanged.
    - Modified or restored files are re-read and updated.
    - Removed files inside library_path are marked missing rather than deleted.
    - Corrupt files and unparseable audio are logged and counted as errors without crashing.

    Args:
        library_path: Directory containing audio files to scan (read-only).
        db_path: Path to the SQLite database.
        progress_callback: Optional progress notification hook.

    Returns:
        ScanSummary: Counts of new, updated, unchanged, missing, and error files.

    Raises:
        ValueError: If library_path is not an existing directory.
    """
    if not library_path.exists() or not library_path.is_dir():
        raise ValueError(f"Library path is not an existing directory: {library_path}")

    canonical_library = library_path.resolve()
    logger.info("Scanning library directory: %s", canonical_library)

    init_db(db_path)
    summary = ScanSummary()

    audio_files = find_audio_files(canonical_library)
    total_files = len(audio_files)

    with get_connection(db_path) as conn:
        existing_tracks = get_existing_tracks(conn)
        scanned_paths_set: set[str] = set()

        for idx, file_path in enumerate(audio_files):
            path_str = str(file_path)
            scanned_paths_set.add(path_str)

            if progress_callback:
                progress_callback(idx + 1, total_files, file_path)

            try:
                stat = file_path.stat()
                mtime = stat.st_mtime
                size = stat.st_size
            except OSError as err:
                logger.warning("Could not stat file %s: %s", file_path, err)
                summary.errors += 1
                continue

            existing = existing_tracks.get(path_str)

            # Incremental check: skip unchanged files
            if (
                existing is not None
                and existing.status == "active"
                and abs(existing.mtime - mtime) < 1e-4
                and existing.size == size
            ):
                summary.unchanged += 1
                continue

            # File is either new, modified, or restored from missing
            try:
                file_hash = compute_file_hash(file_path)
                meta = extract_metadata(file_path)
            except Exception as err:
                logger.warning("Error reading metadata from %s: %s", file_path, err)
                summary.errors += 1
                continue

            with conn:
                if existing is None:
                    insert_track(
                        conn=conn,
                        path=path_str,
                        mtime=mtime,
                        size=size,
                        file_hash=file_hash,
                        duration=meta.duration,
                        bitrate=meta.bitrate,
                        title=meta.title,
                        artist=meta.artist,
                        album_artist=meta.album_artist,
                        album=meta.album,
                        track_no=meta.track_no,
                        track_total=meta.track_total,
                        disc_no=meta.disc_no,
                        disc_total=meta.disc_total,
                        year=meta.year,
                        genre=meta.genre,
                        has_cover=meta.has_cover,
                        tags_json=meta.tags_json,
                    )
                    summary.new += 1
                else:
                    update_track(
                        conn=conn,
                        track_id=existing.id,
                        mtime=mtime,
                        size=size,
                        file_hash=file_hash,
                        duration=meta.duration,
                        bitrate=meta.bitrate,
                        title=meta.title,
                        artist=meta.artist,
                        album_artist=meta.album_artist,
                        album=meta.album,
                        track_no=meta.track_no,
                        track_total=meta.track_total,
                        disc_no=meta.disc_no,
                        disc_total=meta.disc_total,
                        year=meta.year,
                        genre=meta.genre,
                        has_cover=meta.has_cover,
                        tags_json=meta.tags_json,
                    )
                    summary.updated += 1

        # Detect removed files: active tracks under canonical_library that were not found on disk
        missing_ids: list[int] = []
        for path_str, record in existing_tracks.items():
            if record.status == "active" and path_str not in scanned_paths_set:
                try:
                    p = Path(path_str)
                    if p.is_relative_to(canonical_library):
                        missing_ids.append(record.id)
                except ValueError:
                    continue

        if missing_ids:
            with conn:
                updated_missing = mark_tracks_missing(conn, missing_ids)
                summary.missing = updated_missing

    logger.info(
        "Scan complete for %s. New: %d, Updated: %d, Unchanged: %d, Missing: %d, Errors: %d",
        canonical_library,
        summary.new,
        summary.updated,
        summary.unchanged,
        summary.missing,
        summary.errors,
    )
    return summary
