"""Scanner module for traversing local audio libraries and extracting tags.

This module guarantees strict read-only access to audio files. No files will
ever be modified, renamed, moved, retagged, or deleted on disk.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset(
    {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".mp4", ".wma", ".wav", ".aiff"}
)


def is_audio_file(file_path: Path) -> bool:
    """Check if a path points to a supported audio file by extension.

    Args:
        file_path: Filesystem path to evaluate.

    Returns:
        bool: True if extension is supported, False otherwise.
    """
    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS


def scan_directory(library_path: Path, db_path: Path) -> int:
    """Scan an audio directory and record discovered tracks in the database.

    Args:
        library_path: Directory containing audio files to scan (read-only).
        db_path: Path to the SQLite database.

    Returns:
        int: Total number of scanned tracks.
    """
    logger.info("Scanning library directory: %s", library_path)
    raise NotImplementedError("Scanner engine will be implemented in Phase 2.")
