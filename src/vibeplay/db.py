"""Database access and schema management for vibeplay."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    hash TEXT NOT NULL,
    duration REAL,
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tracks_path ON tracks(path);
CREATE INDEX IF NOT EXISTS idx_tracks_hash ON tracks(hash);
CREATE INDEX IF NOT EXISTS idx_tracks_mtime ON tracks(mtime);

CREATE TABLE IF NOT EXISTS enrichment (
    track_id INTEGER PRIMARY KEY,
    mb_recording_id TEXT,
    mb_release_id TEXT,
    mb_artist_id TEXT,
    source TEXT NOT NULL,
    raw_metadata TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_enrichment_mb_recording ON enrichment(mb_recording_id);

CREATE TABLE IF NOT EXISTS features (
    track_id INTEGER PRIMARY KEY,
    analyzer_version TEXT NOT NULL,
    bpm REAL,
    key TEXT,
    scale TEXT,
    loudness REAL,
    danceability REAL,
    energy REAL,
    mood_scores TEXT,
    embedding BLOB,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_features_bpm ON features(bpm);
CREATE INDEX IF NOT EXISTS idx_features_energy ON features(energy);
CREATE INDEX IF NOT EXISTS idx_features_danceability ON features(danceability);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    rules_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (playlist_id, position),
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);

CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create and return a configured SQLite connection.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        sqlite3.Connection: Connection with WAL mode and row factory enabled.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: Path) -> None:
    """Initialize the SQLite database schema if tables do not exist.

    Args:
        db_path: Path to the database file.
    """
    logger.info("Initializing database schema at: %s", db_path)
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    logger.debug("Database schema initialized successfully.")
