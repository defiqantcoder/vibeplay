"""Metadata enrichment module using AcoustID and MusicBrainz.

Generates Chromaprint fingerprints via fpcalc / pyacoustid, queries AcoustID,
and resolves canonical recording, artist, album, and genre tags via MusicBrainz.
Respects MusicBrainz 1 req/sec rate limit, caches responses in SQLite, and
supports resumable execution and retry with backoff.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import acoustid
import musicbrainzngs

from vibeplay.config import get_settings
from vibeplay.db import (
    get_cached_response,
    get_connection,
    get_enrichment_report,
    get_unenriched_tracks,
    init_db,
    insert_or_replace_enrichment,
    set_cached_response,
)
from vibeplay.scanner import _parse_int_pair, _parse_year

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, str], None]


class RateLimiter:
    """Enforces minimum interval between consecutive requests."""

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        self.min_interval = min_interval_seconds
        self.last_request_time = 0.0

    def wait(self) -> None:
        """Block if needed until the minimum interval has elapsed."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()


# Global rate limiter instance for MusicBrainz queries
_mb_rate_limiter = RateLimiter(min_interval_seconds=1.0)


@dataclass
class EnrichmentSummary:
    """Summary of enrichment batch execution."""

    total: int = 0
    matched: int = 0
    needs_review: int = 0
    unmatched: int = 0
    errors: int = 0


@dataclass(frozen=True)
class EnrichmentResult:
    """Resolved metadata for a single track."""

    track_id: int
    mb_recording_id: str | None
    mb_release_id: str | None
    mb_artist_id: str | None
    canonical_title: str | None
    canonical_artist: str | None
    canonical_album_artist: str | None
    canonical_album: str | None
    canonical_year: int | None
    canonical_track_no: int | None
    canonical_track_total: int | None
    canonical_disc_no: int | None
    canonical_disc_total: int | None
    genres_json: str | None
    tags_json: str | None
    confidence: float
    status: str
    source: str
    raw_metadata_json: str


def setup_musicbrainz() -> None:
    """Configure MusicBrainz client user agent and library rate limiting."""
    settings = get_settings()
    musicbrainzngs.set_useragent(
        app=settings.musicbrainz_app,
        version=settings.musicbrainz_version,
        contact=settings.musicbrainz_contact,
    )
    musicbrainzngs.set_rate_limit(
        limit_or_interval=settings.musicbrainz_rate_limit,
        new_requests=1,
    )


def cached_acoustid_lookup(
    conn: Any,
    api_key: str,
    fingerprint: bytes,
    duration: float,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
) -> dict[str, Any] | None:
    """Query AcoustID API with SQLite response caching and retry with backoff.

    Args:
        conn: SQLite connection.
        api_key: AcoustID API key.
        fingerprint: Chromaprint raw or base64 fingerprint bytes.
        duration: Audio duration in seconds.
        max_retries: Maximum number of retry attempts.
        backoff_factor: Multiplier for exponential backoff delay.

    Returns:
        dict[str, Any] | None: AcoustID API response dictionary, or None on failure.
    """
    fp_hash = hashlib.sha256(fingerprint).hexdigest()
    cache_key = f"acoustid:{fp_hash}:{int(duration)}"

    cached = get_cached_response(conn, cache_key)
    if cached:
        logger.debug("Cache hit for AcoustID fingerprint %s", fp_hash[:12])
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    delay = 1.0
    for attempt in range(max_retries):
        try:
            logger.debug("Querying AcoustID API (attempt %d/%d)...", attempt + 1, max_retries)
            response = acoustid.lookup(
                apikey=api_key,
                fingerprint=fingerprint,
                duration=duration,
                meta=["recordings", "releases", "tracks", "compress"],
            )
            response_json = json.dumps(response, ensure_ascii=False)
            set_cached_response(conn, cache_key, "acoustid.lookup", response_json, 200)
            return response
        except acoustid.AcoustidError as err:
            logger.warning("AcoustID API error on attempt %d: %s", attempt + 1, err)
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= backoff_factor
            else:
                return None
        except Exception as err:
            logger.warning("Unexpected network error on AcoustID lookup: %s", err)
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= backoff_factor
            else:
                return None
    return None


def cached_musicbrainz_recording(
    conn: Any,
    mb_recording_id: str,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
) -> dict[str, Any] | None:
    """Query MusicBrainz for a recording by ID with caching and rate limiting.

    Args:
        conn: SQLite connection.
        mb_recording_id: MusicBrainz recording UUID.
        max_retries: Maximum retry attempts on network error.
        backoff_factor: Multiplier for exponential backoff.

    Returns:
        dict[str, Any] | None: MusicBrainz recording dictionary or None.
    """
    cache_key = f"musicbrainz:recording:{mb_recording_id}"
    cached = get_cached_response(conn, cache_key)
    if cached:
        logger.debug("Cache hit for MusicBrainz recording %s", mb_recording_id)
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    setup_musicbrainz()
    delay = 1.0

    for attempt in range(max_retries):
        try:
            _mb_rate_limiter.wait()
            logger.debug(
                "Fetching MusicBrainz recording %s (attempt %d/%d)...",
                mb_recording_id,
                attempt + 1,
                max_retries,
            )
            data = musicbrainzngs.get_recording_by_id(
                mb_recording_id,
                includes=["artists", "releases", "tags"],
            )
            data_json = json.dumps(data, ensure_ascii=False)
            set_cached_response(
                conn, cache_key, "musicbrainz.get_recording_by_id", data_json, 200
            )
            return data
        except musicbrainzngs.MusicBrainzError as err:
            logger.warning("MusicBrainz API error on attempt %d: %s", attempt + 1, err)
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= backoff_factor
            else:
                return None
        except Exception as err:
            logger.warning("Network error on MusicBrainz query: %s", err)
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= backoff_factor
            else:
                return None
    return None


def _pick_best_release(
    releases: list[dict[str, Any]],
    preferred_album: str | None,
) -> dict[str, Any] | None:
    """Select the best matching release from a MusicBrainz release list.

    Prefers official releases matching original album title or earliest official release.

    Args:
        releases: List of release dictionaries.
        preferred_album: Optional album title from original track tags.

    Returns:
        dict[str, Any] | None: Chosen release dictionary.
    """
    if not releases:
        return None

    # Try exact match on album title
    if preferred_album:
        norm_album = preferred_album.strip().lower()
        for rel in releases:
            if rel.get("title", "").strip().lower() == norm_album:
                return rel

    # Prefer official releases
    official = [r for r in releases if r.get("status") == "Official"]
    pool = official if official else releases

    # Sort by date (earliest first if valid year)
    def sort_key(r: dict[str, Any]) -> str:
        return str(r.get("date") or "9999")

    return min(pool, key=sort_key)


def _extract_tags_and_genres(
    recording: dict[str, Any],
    release: dict[str, Any] | None,
) -> tuple[str, str]:
    """Extract and categorize community tags and genres from MusicBrainz objects.

    Args:
        recording: MusicBrainz recording dictionary.
        release: Selected MusicBrainz release dictionary (if any).

    Returns:
        tuple[str, str]: (genres_json, tags_json)
    """
    all_tags: set[str] = set()

    for item in (recording, release):
        if not item:
            continue
        # Direct tag-list
        for tag in item.get("tag-list", []):
            name = tag.get("name", "").strip().lower()
            if name:
                all_tags.add(name)

        # Artist credits tag-lists
        for ac in item.get("artist-credit", []):
            if isinstance(ac, dict) and "artist" in ac:
                for tag in ac["artist"].get("tag-list", []):
                    name = tag.get("name", "").strip().lower()
                    if name:
                        all_tags.add(name)

    genre_keywords = {
        "rock", "pop", "electronic", "jazz", "classical", "hip hop", "ambient",
        "soul", "funk", "folk", "blues", "metal", "indie", "alternative",
        "downtempo", "house", "techno", "r&b", "country", "dance",
    }

    genres = sorted(t for t in all_tags if any(k in t for k in genre_keywords))
    tags = sorted(all_tags)

    return json.dumps(genres, ensure_ascii=False), json.dumps(tags, ensure_ascii=False)


def resolve_track_enrichment(
    conn: Any,
    track: Any,
    acoustid_api_key: str,
    confidence_threshold: float = 0.8,
) -> EnrichmentResult:
    """Fingerprint an audio track, query AcoustID and MusicBrainz, and produce enrichment.

    Args:
        conn: Open SQLite connection.
        track: Track record (sqlite3.Row or TrackRecord).
        acoustid_api_key: AcoustID API key.
        confidence_threshold: Threshold below which match is marked 'needs_review'.

    Returns:
        EnrichmentResult: Resolved canonical metadata and match confidence.
    """
    track_path = Path(track["path"])
    track_id = track["id"]

    # Step 1: Generate Chromaprint fingerprint
    try:
        duration, fingerprint = acoustid.fingerprint_file(str(track_path))
    except Exception as err:
        logger.warning("Fingerprint generation failed for %s: %s", track_path, err)
        return EnrichmentResult(
            track_id=track_id,
            mb_recording_id=None,
            mb_release_id=None,
            mb_artist_id=None,
            canonical_title=None,
            canonical_artist=None,
            canonical_album_artist=None,
            canonical_album=None,
            canonical_year=None,
            canonical_track_no=None,
            canonical_track_total=None,
            canonical_disc_no=None,
            canonical_disc_total=None,
            genres_json=None,
            tags_json=None,
            confidence=0.0,
            status="error",
            source="acoustid",
            raw_metadata_json=json.dumps({"error": str(err)}),
        )

    # Step 2: Query AcoustID API
    acoustid_resp = cached_acoustid_lookup(
        conn=conn,
        api_key=acoustid_api_key,
        fingerprint=fingerprint,
        duration=duration,
    )

    if not acoustid_resp or not acoustid_resp.get("results"):
        logger.info("No AcoustID match found for %s", track_path.name)
        return EnrichmentResult(
            track_id=track_id,
            mb_recording_id=None,
            mb_release_id=None,
            mb_artist_id=None,
            canonical_title=None,
            canonical_artist=None,
            canonical_album_artist=None,
            canonical_album=None,
            canonical_year=None,
            canonical_track_no=None,
            canonical_track_total=None,
            canonical_disc_no=None,
            canonical_disc_total=None,
            genres_json=None,
            tags_json=None,
            confidence=0.0,
            status="unmatched",
            source="acoustid",
            raw_metadata_json=json.dumps(acoustid_resp or {}),
        )

    # Step 3: Pick best AcoustID result and MusicBrainz recording ID
    best_result = None
    best_recording = None
    best_score = 0.0

    for result in acoustid_resp["results"]:
        score = float(result.get("score", 0.0))
        recordings = result.get("recordings", [])
        if recordings and score > best_score:
            best_score = score
            best_result = result
            best_recording = recordings[0]

    if not best_recording or "id" not in best_recording:
        return EnrichmentResult(
            track_id=track_id,
            mb_recording_id=None,
            mb_release_id=None,
            mb_artist_id=None,
            canonical_title=None,
            canonical_artist=None,
            canonical_album_artist=None,
            canonical_album=None,
            canonical_year=None,
            canonical_track_no=None,
            canonical_track_total=None,
            canonical_disc_no=None,
            canonical_disc_total=None,
            genres_json=None,
            tags_json=None,
            confidence=best_score,
            status="unmatched",
            source="acoustid",
            raw_metadata_json=json.dumps(best_result or {}),
        )

    mb_recording_id = best_recording["id"]

    # Step 4: Query MusicBrainz for recording details
    mb_data = cached_musicbrainz_recording(conn=conn, mb_recording_id=mb_recording_id)
    rec_obj = mb_data.get("recording", {}) if mb_data else best_recording

    canonical_title = rec_obj.get("title") or best_recording.get("title")

    # Artist credits
    canonical_artist = rec_obj.get("artist-credit-phrase")
    mb_artist_id = None
    artist_credit = rec_obj.get("artist-credit", [])
    if not canonical_artist and artist_credit:
        first_ac = artist_credit[0]
        if isinstance(first_ac, dict) and "artist" in first_ac:
            canonical_artist = first_ac["artist"].get("name")
            mb_artist_id = first_ac["artist"].get("id")
    elif artist_credit:
        first_ac = artist_credit[0]
        if isinstance(first_ac, dict) and "artist" in first_ac:
            mb_artist_id = first_ac["artist"].get("id")

    if not canonical_artist and best_recording.get("artists"):
        first_art = best_recording["artists"][0]
        canonical_artist = first_art.get("name")
        mb_artist_id = first_art.get("id")

    # Release resolution
    releases = rec_obj.get("release-list") or best_recording.get("releases", [])
    chosen_release = _pick_best_release(releases, preferred_album=track["album"])

    canonical_album = None
    canonical_album_artist = None
    canonical_year = None
    mb_release_id = None
    canonical_track_no = None
    canonical_track_total = None
    canonical_disc_no = None
    canonical_disc_total = None

    if chosen_release:
        mb_release_id = chosen_release.get("id")
        canonical_album = chosen_release.get("title")
        canonical_album_artist = (
            chosen_release.get("artist-credit-phrase") or canonical_artist
        )
        raw_date = chosen_release.get("date")
        if isinstance(raw_date, dict):
            canonical_year = raw_date.get("year")
        else:
            canonical_year = _parse_year(raw_date)

        # Inspect mediums for track/disc position
        for medium in chosen_release.get("mediums", []):
            canonical_disc_no = medium.get("position")
            canonical_track_total = medium.get("track_count")
            for t_item in medium.get("tracks", []):
                if t_item.get("title", "").strip().lower() == str(canonical_title).strip().lower():
                    canonical_track_no = t_item.get("position")
                    break

    # Genres and tags
    genres_json, tags_json = _extract_tags_and_genres(rec_obj, chosen_release)

    # Determine status by confidence threshold
    confidence = round(best_score, 4)
    status = "matched" if confidence >= confidence_threshold else "needs_review"

    raw_combined = {
        "acoustid_result": best_result,
        "musicbrainz_recording": mb_data,
    }

    return EnrichmentResult(
        track_id=track_id,
        mb_recording_id=mb_recording_id,
        mb_release_id=mb_release_id,
        mb_artist_id=mb_artist_id,
        canonical_title=canonical_title,
        canonical_artist=canonical_artist,
        canonical_album_artist=canonical_album_artist,
        canonical_album=canonical_album,
        canonical_year=canonical_year,
        canonical_track_no=canonical_track_no,
        canonical_track_total=canonical_track_total,
        canonical_disc_no=canonical_disc_no,
        canonical_disc_total=canonical_disc_total,
        genres_json=genres_json,
        tags_json=tags_json,
        confidence=confidence,
        status=status,
        source="acoustid_musicbrainz",
        raw_metadata_json=json.dumps(raw_combined, ensure_ascii=False),
    )


def enrich_tracks(
    db_path: Path,
    limit: int | None = None,
    force: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> EnrichmentSummary:
    """Enrich audio tracks in the database using AcoustID and MusicBrainz.

    Resumable if interrupted: tracks are committed as they are processed.
    Caches all network requests in SQLite.

    Args:
        db_path: Path to the SQLite database.
        limit: Optional maximum number of tracks to enrich in this run.
        force: Re-enrich tracks that already have enrichment records.
        progress_callback: Optional progress hook (current, total, track_name).

    Returns:
        EnrichmentSummary: Counts of matched, needs_review, unmatched, and error tracks.

    Raises:
        ValueError: If ACOUSTID_API_KEY is not configured in environment or .env.
    """
    settings = get_settings()
    if not settings.acoustid_api_key:
        raise ValueError(
            "ACOUSTID_API_KEY is required for metadata enrichment. "
            "Please set it in your environment or .env file."
        )

    init_db(db_path)
    summary = EnrichmentSummary()

    with get_connection(db_path) as conn:
        tracks = get_unenriched_tracks(conn, force=force, limit=limit)
        summary.total = len(tracks)

        for idx, track in enumerate(tracks):
            track_name = track["title"] or Path(track["path"]).name
            if progress_callback:
                progress_callback(idx + 1, summary.total, track_name)

            try:
                res = resolve_track_enrichment(
                    conn=conn,
                    track=track,
                    acoustid_api_key=settings.acoustid_api_key,
                    confidence_threshold=settings.enrichment_confidence_threshold,
                )

                with conn:
                    insert_or_replace_enrichment(
                        conn=conn,
                        track_id=res.track_id,
                        mb_recording_id=res.mb_recording_id,
                        mb_release_id=res.mb_release_id,
                        mb_artist_id=res.mb_artist_id,
                        canonical_title=res.canonical_title,
                        canonical_artist=res.canonical_artist,
                        canonical_album_artist=res.canonical_album_artist,
                        canonical_album=res.canonical_album,
                        canonical_year=res.canonical_year,
                        canonical_track_no=res.canonical_track_no,
                        canonical_track_total=res.canonical_track_total,
                        canonical_disc_no=res.canonical_disc_no,
                        canonical_disc_total=res.canonical_disc_total,
                        genres=res.genres_json,
                        tags=res.tags_json,
                        confidence=res.confidence,
                        status=res.status,
                        source=res.source,
                        raw_metadata=res.raw_metadata_json,
                    )

                if res.status == "matched":
                    summary.matched += 1
                elif res.status == "needs_review":
                    summary.needs_review += 1
                elif res.status == "unmatched":
                    summary.unmatched += 1
                else:
                    summary.errors += 1

            except Exception as err:
                logger.warning("Error enriching track %s: %s", track["path"], err)
                summary.errors += 1

    return summary


def get_report_data(db_path: Path) -> list[dict[str, Any]]:
    """Retrieve tracks that are unmatched or below the confidence threshold.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        list[dict[str, Any]]: List of report row dictionaries.
    """
    settings = get_settings()
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = get_enrichment_report(
            conn,
            confidence_threshold=settings.enrichment_confidence_threshold,
        )
        return [dict(row) for row in rows]
