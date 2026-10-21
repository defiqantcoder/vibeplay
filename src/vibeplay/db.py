"""Database access and schema management for vibeplay with versioned migrations."""

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "001_initial_schema",
        """
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
        """,
    ),
    (
        2,
        "002_track_metadata_and_status",
        """
        ALTER TABLE tracks ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
        ALTER TABLE tracks ADD COLUMN bitrate INTEGER;
        ALTER TABLE tracks ADD COLUMN title TEXT;
        ALTER TABLE tracks ADD COLUMN artist TEXT;
        ALTER TABLE tracks ADD COLUMN album_artist TEXT;
        ALTER TABLE tracks ADD COLUMN album TEXT;
        ALTER TABLE tracks ADD COLUMN track_no INTEGER;
        ALTER TABLE tracks ADD COLUMN track_total INTEGER;
        ALTER TABLE tracks ADD COLUMN disc_no INTEGER;
        ALTER TABLE tracks ADD COLUMN disc_total INTEGER;
        ALTER TABLE tracks ADD COLUMN year INTEGER;
        ALTER TABLE tracks ADD COLUMN genre TEXT;
        ALTER TABLE tracks ADD COLUMN has_cover INTEGER NOT NULL DEFAULT 0;

        CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
        CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
        CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album);
        """,
    ),
    (
        3,
        "003_enrichment_columns_cache_and_view",
        """
        ALTER TABLE enrichment ADD COLUMN canonical_title TEXT;
        ALTER TABLE enrichment ADD COLUMN canonical_artist TEXT;
        ALTER TABLE enrichment ADD COLUMN canonical_album_artist TEXT;
        ALTER TABLE enrichment ADD COLUMN canonical_album TEXT;
        ALTER TABLE enrichment ADD COLUMN canonical_year INTEGER;
        ALTER TABLE enrichment ADD COLUMN canonical_track_no INTEGER;
        ALTER TABLE enrichment ADD COLUMN canonical_track_total INTEGER;
        ALTER TABLE enrichment ADD COLUMN canonical_disc_no INTEGER;
        ALTER TABLE enrichment ADD COLUMN canonical_disc_total INTEGER;
        ALTER TABLE enrichment ADD COLUMN genres TEXT;
        ALTER TABLE enrichment ADD COLUMN tags TEXT;
        ALTER TABLE enrichment ADD COLUMN confidence REAL DEFAULT 0.0;
        ALTER TABLE enrichment ADD COLUMN status TEXT NOT NULL DEFAULT 'matched';

        CREATE INDEX IF NOT EXISTS idx_enrichment_status ON enrichment(status);
        CREATE INDEX IF NOT EXISTS idx_enrichment_confidence ON enrichment(confidence);

        CREATE TABLE IF NOT EXISTS network_cache (
            cache_key TEXT PRIMARY KEY,
            endpoint TEXT NOT NULL,
            response_json TEXT NOT NULL,
            status_code INTEGER NOT NULL DEFAULT 200,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_network_cache_endpoint ON network_cache(endpoint);

        DROP VIEW IF EXISTS v_tracks_best_value;
        CREATE VIEW v_tracks_best_value AS
        SELECT
            t.id AS track_id,
            t.path,
            t.duration,
            t.bitrate,
            t.has_cover,
            t.status AS track_status,
            COALESCE(e.canonical_title, t.title) AS title,
            COALESCE(e.canonical_artist, t.artist) AS artist,
            COALESCE(e.canonical_album_artist, t.album_artist, e.canonical_artist, t.artist) AS album_artist,
            COALESCE(e.canonical_album, t.album) AS album,
            COALESCE(e.canonical_track_no, t.track_no) AS track_no,
            COALESCE(e.canonical_track_total, t.track_total) AS track_total,
            COALESCE(e.canonical_disc_no, t.disc_no) AS disc_no,
            COALESCE(e.canonical_disc_total, t.disc_total) AS disc_total,
            COALESCE(e.canonical_year, t.year) AS year,
            COALESCE(e.genres, t.genre) AS genre,
            t.title AS original_title,
            t.artist AS original_artist,
            t.album AS original_album,
            t.year AS original_year,
            t.genre AS original_genre,
            e.canonical_title,
            e.canonical_artist,
            e.canonical_album,
            e.canonical_year,
            e.genres AS enriched_genres,
            e.tags AS enriched_tags,
            e.mb_recording_id,
            e.mb_release_id,
            e.mb_artist_id,
            e.confidence,
            e.status AS enrichment_status,
            e.fetched_at AS enriched_at
        FROM tracks t
        LEFT JOIN enrichment e ON t.id = e.track_id;
        """,
    ),
]


@dataclass(frozen=True)
class TrackRecord:
    """Represents a track record in the SQLite database."""

    id: int
    path: str
    mtime: float
    size: int
    hash: str
    status: str
    duration: float | None = None
    bitrate: int | None = None
    title: str | None = None
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    track_no: int | None = None
    track_total: int | None = None
    disc_no: int | None = None
    disc_total: int | None = None
    year: int | None = None
    genre: str | None = None
    has_cover: bool = False
    tags: str | None = None


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


def migrate_db(conn: sqlite3.Connection) -> int:
    """Run all pending schema migrations inside transactions.

    Args:
        conn: Open SQLite connection.

    Returns:
        int: Number of newly applied migrations.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM schema_migrations")
    applied_versions = {row[0] for row in cursor.fetchall()}

    applied_count = 0
    for version, name, script in MIGRATIONS:
        if version not in applied_versions:
            logger.info("Applying migration %03d_%s", version, name)
            with conn:
                conn.executescript(script)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, name),
                )
            applied_count += 1

    return applied_count


def init_db(db_path: Path) -> None:
    """Initialize or upgrade the SQLite database schema.

    Args:
        db_path: Path to the database file.
    """
    logger.debug("Initializing database schema at: %s", db_path)
    with get_connection(db_path) as conn:
        migrate_db(conn)


def get_existing_tracks(conn: sqlite3.Connection) -> dict[str, TrackRecord]:
    """Retrieve all existing track records keyed by canonical path string.

    Args:
        conn: Open SQLite connection.

    Returns:
        dict[str, TrackRecord]: Mapping of path -> TrackRecord.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id, path, mtime, size, hash, status, duration, bitrate,
            title, artist, album_artist, album, track_no, track_total,
            disc_no, disc_total, year, genre, has_cover, tags
        FROM tracks
        """
    )
    tracks: dict[str, TrackRecord] = {}
    for row in cursor.fetchall():
        tracks[row["path"]] = TrackRecord(
            id=row["id"],
            path=row["path"],
            mtime=row["mtime"],
            size=row["size"],
            hash=row["hash"],
            status=row["status"],
            duration=row["duration"],
            bitrate=row["bitrate"],
            title=row["title"],
            artist=row["artist"],
            album_artist=row["album_artist"],
            album=row["album"],
            track_no=row["track_no"],
            track_total=row["track_total"],
            disc_no=row["disc_no"],
            disc_total=row["disc_total"],
            year=row["year"],
            genre=row["genre"],
            has_cover=bool(row["has_cover"]),
            tags=row["tags"],
        )
    return tracks


def insert_track(
    conn: sqlite3.Connection,
    path: str,
    mtime: float,
    size: int,
    file_hash: str,
    duration: float | None,
    bitrate: int | None,
    title: str | None,
    artist: str | None,
    album_artist: str | None,
    album: str | None,
    track_no: int | None,
    track_total: int | None,
    disc_no: int | None,
    disc_total: int | None,
    year: int | None,
    genre: str | None,
    has_cover: bool,
    tags_json: str,
) -> int:
    """Insert a new track record into the database.

    Args:
        conn: Open SQLite connection.
        path: Path string of the audio file.
        mtime: File modification timestamp.
        size: File size in bytes.
        file_hash: SHA-256 hash string.
        duration: Audio duration in seconds.
        bitrate: Audio bitrate in bps.
        title: Track title.
        artist: Track artist.
        album_artist: Album artist.
        album: Album title.
        track_no: Track number.
        track_total: Total tracks in album.
        disc_no: Disc number.
        disc_total: Total discs in album.
        year: Release year.
        genre: Music genre.
        has_cover: Whether embedded artwork was detected.
        tags_json: Serialized JSON representation of all tags.

    Returns:
        int: The inserted track ID.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO tracks (
            path, mtime, size, hash, duration, bitrate,
            title, artist, album_artist, album, track_no, track_total,
            disc_no, disc_total, year, genre, has_cover, tags, status,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, 'active',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        (
            path,
            mtime,
            size,
            file_hash,
            duration,
            bitrate,
            title,
            artist,
            album_artist,
            album,
            track_no,
            track_total,
            disc_no,
            disc_total,
            year,
            genre,
            1 if has_cover else 0,
            tags_json,
        ),
    )
    return cursor.lastrowid or 0


def update_track(
    conn: sqlite3.Connection,
    track_id: int,
    mtime: float,
    size: int,
    file_hash: str,
    duration: float | None,
    bitrate: int | None,
    title: str | None,
    artist: str | None,
    album_artist: str | None,
    album: str | None,
    track_no: int | None,
    track_total: int | None,
    disc_no: int | None,
    disc_total: int | None,
    year: int | None,
    genre: str | None,
    has_cover: bool,
    tags_json: str,
) -> None:
    """Update an existing track record and reactivate it.

    Args:
        conn: Open SQLite connection.
        track_id: Database track ID.
        mtime: New file modification timestamp.
        size: New file size in bytes.
        file_hash: New SHA-256 hash string.
        duration: Audio duration in seconds.
        bitrate: Audio bitrate in bps.
        title: Track title.
        artist: Track artist.
        album_artist: Album artist.
        album: Album title.
        track_no: Track number.
        track_total: Total tracks in album.
        disc_no: Disc number.
        disc_total: Total discs in album.
        year: Release year.
        genre: Music genre.
        has_cover: Whether embedded artwork was detected.
        tags_json: Serialized JSON representation of all tags.
    """
    conn.execute(
        """
        UPDATE tracks
        SET
            mtime = ?,
            size = ?,
            hash = ?,
            duration = ?,
            bitrate = ?,
            title = ?,
            artist = ?,
            album_artist = ?,
            album = ?,
            track_no = ?,
            track_total = ?,
            disc_no = ?,
            disc_total = ?,
            year = ?,
            genre = ?,
            has_cover = ?,
            tags = ?,
            status = 'active',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            mtime,
            size,
            file_hash,
            duration,
            bitrate,
            title,
            artist,
            album_artist,
            album,
            track_no,
            track_total,
            disc_no,
            disc_total,
            year,
            genre,
            1 if has_cover else 0,
            tags_json,
            track_id,
        ),
    )


def mark_tracks_missing(conn: sqlite3.Connection, track_ids: list[int]) -> int:
    """Mark a list of track IDs as missing without deleting rows.

    Args:
        conn: Open SQLite connection.
        track_ids: List of track IDs to mark as missing.

    Returns:
        int: Number of tracks updated.
    """
    if not track_ids:
        return 0
    cursor = conn.cursor()
    cursor.executemany(
        """
        UPDATE tracks
        SET status = 'missing', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status != 'missing'
        """,
        [(tid,) for tid in track_ids],
    )
    return cursor.rowcount


def get_cached_response(conn: sqlite3.Connection, cache_key: str) -> str | None:
    """Retrieve cached response JSON from network_cache.

    Args:
        conn: Open SQLite connection.
        cache_key: Unique cache key identifier.

    Returns:
        str | None: Cached JSON string or None if cache miss.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT response_json FROM network_cache WHERE cache_key = ?",
        (cache_key,),
    )
    row = cursor.fetchone()
    return row["response_json"] if row else None


def set_cached_response(
    conn: sqlite3.Connection,
    cache_key: str,
    endpoint: str,
    response_json: str,
    status_code: int = 200,
) -> None:
    """Store or update a response JSON string in network_cache.

    Args:
        conn: Open SQLite connection.
        cache_key: Unique cache key identifier.
        endpoint: API endpoint name or URL.
        response_json: Serialized JSON payload.
        status_code: HTTP status code.
    """
    conn.execute(
        """
        INSERT INTO network_cache (cache_key, endpoint, response_json, status_code)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            response_json = excluded.response_json,
            status_code = excluded.status_code,
            created_at = CURRENT_TIMESTAMP
        """,
        (cache_key, endpoint, response_json, status_code),
    )


def get_unenriched_tracks(
    conn: sqlite3.Connection,
    force: bool = False,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Fetch active tracks requiring metadata enrichment.

    Args:
        conn: Open SQLite connection.
        force: If True, include tracks that already have enrichment records.
        limit: Optional maximum number of tracks to return.

    Returns:
        list[sqlite3.Row]: Track rows.
    """
    cursor = conn.cursor()
    query = """
        SELECT t.*
        FROM tracks t
        LEFT JOIN enrichment e ON t.id = e.track_id
        WHERE t.status = 'active'
    """
    if not force:
        query += " AND e.track_id IS NULL"

    query += " ORDER BY t.id ASC"
    if limit is not None:
        query += f" LIMIT {int(limit)}"

    cursor.execute(query)
    return cursor.fetchall()


def insert_or_replace_enrichment(
    conn: sqlite3.Connection,
    track_id: int,
    mb_recording_id: str | None,
    mb_release_id: str | None,
    mb_artist_id: str | None,
    canonical_title: str | None,
    canonical_artist: str | None,
    canonical_album_artist: str | None,
    canonical_album: str | None,
    canonical_year: int | None,
    canonical_track_no: int | None,
    canonical_track_total: int | None,
    canonical_disc_no: int | None,
    canonical_disc_total: int | None,
    genres: str | None,
    tags: str | None,
    confidence: float,
    status: str,
    source: str,
    raw_metadata: str,
) -> None:
    """Insert or replace an enrichment record for a track.

    Args:
        conn: Open SQLite connection.
        track_id: ID of the track.
        mb_recording_id: MusicBrainz recording UUID.
        mb_release_id: MusicBrainz release UUID.
        mb_artist_id: MusicBrainz artist UUID.
        canonical_title: Normalized track title.
        canonical_artist: Normalized artist name.
        canonical_album_artist: Normalized album artist name.
        canonical_album: Normalized album title.
        canonical_year: Normalized release year.
        canonical_track_no: Track number.
        canonical_track_total: Total track count.
        canonical_disc_no: Disc number.
        canonical_disc_total: Total disc count.
        genres: Serialized genres JSON.
        tags: Serialized tags JSON.
        confidence: Match confidence (0.0 to 1.0).
        status: Match status ('matched', 'needs_review', 'unmatched', 'error').
        source: Enrichment source string.
        raw_metadata: Raw API response JSON string.
    """
    conn.execute(
        """
        INSERT INTO enrichment (
            track_id, mb_recording_id, mb_release_id, mb_artist_id,
            canonical_title, canonical_artist, canonical_album_artist, canonical_album,
            canonical_year, canonical_track_no, canonical_track_total,
            canonical_disc_no, canonical_disc_total,
            genres, tags, confidence, status, source, raw_metadata, fetched_at
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
        )
        ON CONFLICT(track_id) DO UPDATE SET
            mb_recording_id = excluded.mb_recording_id,
            mb_release_id = excluded.mb_release_id,
            mb_artist_id = excluded.mb_artist_id,
            canonical_title = excluded.canonical_title,
            canonical_artist = excluded.canonical_artist,
            canonical_album_artist = excluded.canonical_album_artist,
            canonical_album = excluded.canonical_album,
            canonical_year = excluded.canonical_year,
            canonical_track_no = excluded.canonical_track_no,
            canonical_track_total = excluded.canonical_track_total,
            canonical_disc_no = excluded.canonical_disc_no,
            canonical_disc_total = excluded.canonical_disc_total,
            genres = excluded.genres,
            tags = excluded.tags,
            confidence = excluded.confidence,
            status = excluded.status,
            source = excluded.source,
            raw_metadata = excluded.raw_metadata,
            fetched_at = CURRENT_TIMESTAMP
        """,
        (
            track_id,
            mb_recording_id,
            mb_release_id,
            mb_artist_id,
            canonical_title,
            canonical_artist,
            canonical_album_artist,
            canonical_album,
            canonical_year,
            canonical_track_no,
            canonical_track_total,
            canonical_disc_no,
            canonical_disc_total,
            genres,
            tags,
            confidence,
            status,
            source,
            raw_metadata,
        ),
    )


def get_enrichment_report(
    conn: sqlite3.Connection,
    confidence_threshold: float,
) -> list[sqlite3.Row]:
    """Retrieve tracks that are unmatched, low-confidence, or not enriched.

    Args:
        conn: Open SQLite connection.
        confidence_threshold: Threshold below which matches need review.

    Returns:
        list[sqlite3.Row]: Rows from v_tracks_best_value needing attention.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            track_id, path, original_title, original_artist, original_album,
            canonical_title, canonical_artist, canonical_album,
            confidence, enrichment_status
        FROM v_tracks_best_value
        WHERE track_status = 'active'
          AND (
              enrichment_status IS NULL
              OR enrichment_status IN ('unmatched', 'needs_review', 'error')
              OR confidence < ?
          )
        ORDER BY track_id ASC
        """,
        (confidence_threshold,),
    )
    return cursor.fetchall()
