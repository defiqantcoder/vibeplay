"""Database access and schema management for vibeplay with versioned migrations."""

import json
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
    (
        4,
        "004_job_runs",
        """
        CREATE TABLE IF NOT EXISTS job_runs (
            id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            total_items INTEGER DEFAULT 0,
            processed_items INTEGER DEFAULT 0,
            current_item_name TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_job_runs_status ON job_runs(status);
        CREATE INDEX IF NOT EXISTS idx_job_runs_type ON job_runs(job_type);
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
    applied_versions = {row[0] for row in cursor}

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
    for row in cursor:
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
    duration: float | None = None,
    bitrate: int | None = None,
    title: str | None = None,
    artist: str | None = None,
    album_artist: str | None = None,
    album: str | None = None,
    track_no: int | None = None,
    track_total: int | None = None,
    disc_no: int | None = None,
    disc_total: int | None = None,
    year: int | None = None,
    genre: str | None = None,
    has_cover: bool = False,
    tags_json: str = "{}",
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
    placeholders = ",".join("?" for _ in track_ids)
    cursor.execute(
        f"""
        UPDATE tracks
        SET status = 'missing', updated_at = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders}) AND status != 'missing'
        """,
        track_ids,
    )
    return cursor.rowcount


def get_cached_response(
    conn: sqlite3.Connection,
    cache_key: str,
    max_age_days: int | None = None,
) -> str | None:
    """Retrieve cached response JSON from network_cache.

    Args:
        conn: Open SQLite connection.
        cache_key: Unique cache key identifier.
        max_age_days: Optional TTL expiration threshold in days.

    Returns:
        str | None: Cached JSON string or None if cache miss or expired.
    """
    cursor = conn.cursor()
    if max_age_days is not None:
        cursor.execute(
            f"""
            SELECT response_json
            FROM network_cache
            WHERE cache_key = ? AND created_at >= datetime('now', '-{int(max_age_days)} days')
            """,
            (cache_key,),
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute("DELETE FROM network_cache WHERE cache_key = ?", (cache_key,))
            return None
        return row["response_json"]

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


def insert_or_replace_features(
    conn: sqlite3.Connection,
    track_id: int,
    analyzer_version: str,
    bpm: float | None,
    key: str | None,
    scale: str | None,
    loudness: float | None,
    danceability: float | None,
    energy: float | None,
    mood_scores_json: str,
    embedding_blob: bytes,
) -> None:
    """Insert or replace extracted audio features for a track.

    Args:
        conn: Open SQLite connection.
        track_id: Track ID.
        analyzer_version: Version identifier of the analyzer used.
        bpm: Detected tempo in BPM.
        key: Musical key (e.g. 'C', 'A#').
        scale: Musical scale ('major' or 'minor').
        loudness: Integrated loudness in LUFS or dB.
        danceability: Danceability score (0.0 to 1.0).
        energy: Energy score (0.0 to 1.0).
        mood_scores_json: JSON string of mood probabilities.
        embedding_blob: Binary serialized float32 embedding vector.
    """
    conn.execute(
        """
        INSERT INTO features (
            track_id, analyzer_version, bpm, key, scale,
            loudness, danceability, energy, mood_scores, embedding,
            analyzed_at
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT(track_id) DO UPDATE SET
            analyzer_version = excluded.analyzer_version,
            bpm = excluded.bpm,
            key = excluded.key,
            scale = excluded.scale,
            loudness = excluded.loudness,
            danceability = excluded.danceability,
            energy = excluded.energy,
            mood_scores = excluded.mood_scores,
            embedding = excluded.embedding,
            analyzed_at = CURRENT_TIMESTAMP
        """,
        (
            track_id,
            analyzer_version,
            bpm,
            key,
            scale,
            loudness,
            danceability,
            energy,
            mood_scores_json,
            sqlite3.Binary(embedding_blob),
        ),
    )


def get_unanalyzed_tracks(
    conn: sqlite3.Connection,
    analyzer_version: str,
    force: bool = False,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Fetch active tracks requiring audio feature analysis.

    Skips tracks already analyzed with current analyzer_version unless force is True.

    Args:
        conn: Open SQLite connection.
        analyzer_version: Expected analyzer version string.
        force: If True, re-analyze tracks regardless of existing features.
        limit: Optional maximum number of tracks to return.

    Returns:
        list[sqlite3.Row]: Tracks needing analysis.
    """
    cursor = conn.cursor()
    query = """
        SELECT t.id, t.path, t.duration, t.title, t.artist
        FROM tracks t
        LEFT JOIN features f ON t.id = f.track_id
        WHERE t.status = 'active'
    """
    params: list[str] = []
    if not force:
        query += " AND (f.track_id IS NULL OR f.analyzer_version != ?)"
        params.append(analyzer_version)

    query += " ORDER BY t.id ASC"
    if limit is not None:
        query += f" LIMIT {int(limit)}"

    cursor.execute(query, params)
    return cursor.fetchall()


def get_total_active_tracks_count(conn: sqlite3.Connection) -> int:
    """Return the total number of active tracks in the database.

    Args:
        conn: Open SQLite connection.

    Returns:
        int: Total count of active tracks.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM tracks WHERE status = 'active'")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def get_tracks_with_features(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Retrieve all tracks that have extracted audio features.

    Joins the features table with v_tracks_best_value to provide metadata
    alongside numerical audio characteristics.

    Args:
        conn: Open SQLite connection.

    Returns:
        list[sqlite3.Row]: Rows containing track metadata and audio features.
    """
    cursor = conn.cursor()
    query = """
        SELECT
            f.track_id,
            v.path,
            v.duration,
            v.title,
            v.artist,
            v.album_artist,
            v.album,
            v.year,
            v.genre,
            v.mb_recording_id,
            v.enriched_genres,
            v.enriched_tags,
            f.analyzer_version,
            f.bpm,
            f.key,
            f.scale,
            f.loudness,
            f.danceability,
            f.energy,
            f.mood_scores,
            f.embedding
        FROM features f
        JOIN v_tracks_best_value v ON f.track_id = v.track_id
        WHERE v.track_status = 'active'
        ORDER BY f.track_id ASC
    """
    cursor.execute(query)
    return cursor.fetchall()


def get_tracks_with_features_by_ids(
    conn: sqlite3.Connection, track_ids: list[int]
) -> list[sqlite3.Row]:
    """Retrieve track metadata and features for specific track IDs.

    Args:
        conn: Open SQLite connection.
        track_ids: List of track IDs to query.

    Returns:
        list[sqlite3.Row]: Rows containing track metadata and audio features.
    """
    if not track_ids:
        return []

    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(track_ids))
    query = f"""
        SELECT
            f.track_id,
            v.path,
            v.duration,
            v.title,
            v.artist,
            v.album_artist,
            v.album,
            v.year,
            v.genre,
            v.mb_recording_id,
            v.enriched_genres,
            v.enriched_tags,
            f.analyzer_version,
            f.bpm,
            f.key,
            f.scale,
            f.loudness,
            f.danceability,
            f.energy,
            f.mood_scores,
            f.embedding
        FROM features f
        JOIN v_tracks_best_value v ON f.track_id = v.track_id
        WHERE f.track_id IN ({placeholders})
    """
    cursor.execute(query, track_ids)
    return cursor.fetchall()


def get_features_checksum(conn: sqlite3.Connection) -> str:
    """Calculate a deterministic hash over the current features data.

    Used for invalidating cached vibe vectors on disk when underlying
    features are modified or added.

    Args:
        conn: Open SQLite connection.

    Returns:
        str: Hexadecimal SHA-256 digest of features data.
    """
    import hashlib

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT track_id, analyzer_version, bpm, loudness, danceability, energy, mood_scores, length(embedding)
        FROM features
        ORDER BY track_id ASC
        """
    )
    rows = cursor.fetchall()
    hasher = hashlib.sha256()
    for row in rows:
        row_str = "|".join(str(val) if val is not None else "" for val in row)
        hasher.update(row_str.encode("utf-8"))
    return hasher.hexdigest()


def create_playlist(
    conn: sqlite3.Connection,
    name: str,
    description: str | None = None,
    rules_json: str | None = None,
) -> int:
    """Create a new playlist record in the database.

    Args:
        conn: Open SQLite connection.
        name: Name of the playlist.
        description: Optional textual description or notes.
        rules_json: Optional JSON string recording generation parameters.

    Returns:
        int: The newly created playlist ID.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO playlists (name, description, rules_json, created_at, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (name, description, rules_json),
    )
    return cursor.lastrowid or 0


def add_tracks_to_playlist(
    conn: sqlite3.Connection,
    playlist_id: int,
    track_ids: list[int],
) -> None:
    """Associate ordered tracks with a playlist.

    Args:
        conn: Open SQLite connection.
        playlist_id: Database ID of the target playlist.
        track_ids: Ordered list of track IDs to add (1-indexed position).
    """
    cursor = conn.cursor()
    items = [(playlist_id, tid, pos) for pos, tid in enumerate(track_ids, start=1)]
    cursor.executemany(
        """
        INSERT OR REPLACE INTO playlist_tracks (playlist_id, track_id, position, added_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """,
        items,
    )


def get_playlist(conn: sqlite3.Connection, playlist_id: int) -> sqlite3.Row | None:
    """Retrieve metadata for a specific playlist.

    Args:
        conn: Open SQLite connection.
        playlist_id: Database ID of the playlist.

    Returns:
        sqlite3.Row | None: Playlist row or None if not found.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, name, description, rules_json, created_at, updated_at
        FROM playlists
        WHERE id = ?
        """,
        (playlist_id,),
    )
    return cursor.fetchone()


def get_playlist_tracks(
    conn: sqlite3.Connection,
    playlist_id: int,
) -> list[sqlite3.Row]:
    """Retrieve ordered tracks with rich metadata and features for a playlist.

    Args:
        conn: Open SQLite connection.
        playlist_id: Database ID of the playlist.

    Returns:
        list[sqlite3.Row]: Track rows ordered by position.
    """
    cursor = conn.cursor()
    query = """
        SELECT
            pt.position,
            t.id AS track_id,
            t.path,
            t.duration,
            v.title,
            v.artist,
            v.album_artist,
            v.album,
            v.genre,
            v.year,
            v.mb_recording_id,
            f.bpm,
            f.key,
            f.scale,
            f.energy,
            f.danceability,
            f.loudness,
            f.mood_scores
        FROM playlist_tracks pt
        JOIN tracks t ON pt.track_id = t.id
        LEFT JOIN v_tracks_best_value v ON pt.track_id = v.track_id
        LEFT JOIN features f ON pt.track_id = f.track_id
        WHERE pt.playlist_id = ?
        ORDER BY pt.position ASC
    """
    cursor.execute(query, (playlist_id,))
    return cursor.fetchall()


def list_playlists(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """List all saved playlists with track counts and total durations.

    Args:
        conn: Open SQLite connection.

    Returns:
        list[sqlite3.Row]: Playlists with aggregated track metrics.
    """
    cursor = conn.cursor()
    query = """
        SELECT
            p.id,
            p.name,
            p.description,
            p.rules_json,
            p.created_at,
            COUNT(pt.track_id) AS track_count,
            COALESCE(SUM(t.duration), 0.0) AS total_duration
        FROM playlists p
        LEFT JOIN playlist_tracks pt ON p.id = pt.playlist_id
        LEFT JOIN tracks t ON pt.track_id = t.id
        GROUP BY p.id
        ORDER BY p.id DESC
    """
    cursor.execute(query)
    return cursor.fetchall()


def delete_playlist(conn: sqlite3.Connection, playlist_id: int) -> bool:
    """Delete a playlist and its associated tracks.

    Args:
        conn: Open SQLite connection.
        playlist_id: Database ID of the playlist to delete.

    Returns:
        bool: True if a playlist record was deleted, False otherwise.
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    return cursor.rowcount > 0


def get_llm_cache(
    conn: sqlite3.Connection,
    prompt_hash: str,
    max_age_days: int | None = None,
) -> str | None:
    """Retrieve cached LLM response for a given SHA256 prompt hash.

    Args:
        conn: Open SQLite connection.
        prompt_hash: Hexadecimal SHA256 hash string.
        max_age_days: Optional TTL expiration threshold in days.

    Returns:
        str | None: Cached JSON/text response, or None if not found or expired.
    """
    cursor = conn.cursor()
    if max_age_days is not None:
        cursor.execute(
            f"""
            SELECT response
            FROM llm_cache
            WHERE prompt_hash = ? AND created_at >= datetime('now', '-{int(max_age_days)} days')
            """,
            (prompt_hash,),
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute("DELETE FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,))
            return None
        return row["response"]

    cursor.execute(
        "SELECT response FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,)
    )
    row = cursor.fetchone()
    return row["response"] if row else None


def cleanup_expired_caches(
    conn: sqlite3.Connection, max_age_days: int = 30
) -> dict[str, int]:
    """Prune cached LLM prompts and network metadata responses older than max_age_days.

    Enforces privacy data retention policies and removes stale cached API data.

    Args:
        conn: Open SQLite connection.
        max_age_days: Expiration threshold in days (default: 30).

    Returns:
        dict[str, int]: Deleted records count {'llm_cache': N, 'network_cache': M}.
    """
    cursor = conn.cursor()
    cursor.execute(
        f"DELETE FROM llm_cache WHERE created_at < datetime('now', '-{int(max_age_days)} days')"
    )
    llm_count = cursor.rowcount

    cursor.execute(
        f"DELETE FROM network_cache WHERE created_at < datetime('now', '-{int(max_age_days)} days')"
    )
    net_count = cursor.rowcount

    logger.info(
        "Cleaned expired caches (> %d days): %d LLM records, %d network records",
        max_age_days,
        llm_count,
        net_count,
    )
    return {"llm_cache": max(0, llm_count), "network_cache": max(0, net_count)}


def purge_all_caches(conn: sqlite3.Connection) -> dict[str, int]:
    """Purge all cached LLM prompts and network API responses unconditionally.

    Args:
        conn: Open SQLite connection.

    Returns:
        dict[str, int]: Deleted records count {'llm_cache': N, 'network_cache': M}.
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM llm_cache")
    llm_count = cursor.rowcount

    cursor.execute("DELETE FROM network_cache")
    net_count = cursor.rowcount

    logger.info(
        "Purged all local cache tables: %d LLM records, %d network records",
        llm_count,
        net_count,
    )
    return {"llm_cache": max(0, llm_count), "network_cache": max(0, net_count)}


def set_llm_cache(
    conn: sqlite3.Connection, prompt_hash: str, prompt: str, response: str, model: str
) -> None:
    """Insert or replace a cached LLM response.

    Args:
        conn: Open SQLite connection.
        prompt_hash: Hexadecimal SHA256 hash string.
        prompt: Raw prompt text sent to LLM.
        response: Response text received from LLM.
        model: Model identifier used for generation.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO llm_cache (prompt_hash, prompt, response, model, created_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (prompt_hash, prompt, response, model),
    )


def update_track_vibe_tags(
    conn: sqlite3.Connection,
    track_id: int,
    mood_tags: list[str],
    genre_tags: list[str],
) -> None:
    """Persist generated mood and genre tags for a track.

    Args:
        conn: Open SQLite connection.
        track_id: Database ID of the track.
        mood_tags: List of descriptive mood tags.
        genre_tags: List of descriptive genre tags.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT track_id, tags, genres FROM enrichment WHERE track_id = ?",
        (track_id,),
    )
    row = cursor.fetchone()

    combined_tags_json = json.dumps(mood_tags)
    combined_genres_json = json.dumps(genre_tags)

    if row:
        cursor.execute(
            """
            UPDATE enrichment
            SET tags = ?, genres = ?, fetched_at = CURRENT_TIMESTAMP
            WHERE track_id = ?
            """,
            (combined_tags_json, combined_genres_json, track_id),
        )
    else:
        cursor.execute(
            """
            INSERT INTO enrichment (track_id, source, tags, genres, status, confidence, fetched_at)
            VALUES (?, 'llm', ?, ?, 'matched', 1.0, CURRENT_TIMESTAMP)
            """,
            (track_id, combined_tags_json, combined_genres_json),
        )

    # Also update tracks.tags for quick reference
    cursor.execute(
        "UPDATE tracks SET tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (combined_tags_json, track_id),
    )
