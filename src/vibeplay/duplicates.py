"""Duplicate detection engine for finding redundant audio files."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from vibeplay.db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    """A group of tracks that are likely duplicates."""

    group_id: str
    reason: str
    tracks: list[dict[str, Any]]
    keep_track_id: int | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "group_id": self.group_id,
            "reason": self.reason,
            "tracks": self.tracks,
            "keep_track_id": self.keep_track_id,
        }


def _determine_keep_track(tracks: list[dict[str, Any]]) -> int | None:
    """Determine the best track to keep based on bitrate and format."""
    if not tracks:
        return None

    best_track = None
    best_score = -1

    for track in tracks:
        score = 0
        path = track.get("path", "").lower()
        if path.endswith(".flac") or path.endswith(".alac") or path.endswith(".wav"):
            score += 1000000  # Prefer lossless

        bitrate = track.get("bitrate")
        if bitrate is not None:
            score += bitrate

        if score > best_score:
            best_score = score
            best_track = track

    return best_track["id"] if best_track else None


def find_duplicates(db_path: str) -> list[DuplicateGroup]:
    """Find likely duplicate tracks in the database."""
    groups = []

    with get_connection(Path(db_path)) as conn:
        conn.row_factory = dict_factory
        cursor = conn.cursor()

        # 1. Exact MusicBrainz Recording ID matches
        cursor.execute("""
            SELECT t.id, t.path, t.duration, t.bitrate, t.title, t.artist, t.album, e.mb_recording_id
            FROM tracks t
            JOIN enrichment e ON t.id = e.track_id
            WHERE e.mb_recording_id IS NOT NULL AND t.status = 'active'
        """)
        mb_tracks = cursor.fetchall()

        mb_groups = defaultdict(list)
        for t in mb_tracks:
            mb_groups[t["mb_recording_id"]].append(t)

        for mb_id, tracks in mb_groups.items():
            if len(tracks) > 1:
                keep_id = _determine_keep_track(tracks)
                groups.append(
                    DuplicateGroup(
                        group_id=f"mb:{mb_id}",
                        reason="MusicBrainz Recording ID match",
                        tracks=tracks,
                        keep_track_id=keep_id,
                    )
                )

        # 2. Fingerprint similarity + duration match (within 2 seconds)
        # Note: AcoustID/Chromaprint fingerprint isn't directly stored in a readily comparable format in standard tables based on SPEC.md.
        # We will use title + artist + duration as a proxy for fingerprint if AcoustID isn't directly queryable for similarity in SQLite.
        # Actually, let's use exact Artist + Title + Duration (within 2s) for the non-MB fallback.

        cursor.execute("""
            SELECT id, path, duration, bitrate, LOWER(TRIM(title)) as norm_title, LOWER(TRIM(artist)) as norm_artist, title, artist, album
            FROM tracks
            WHERE status = 'active' AND title IS NOT NULL AND artist IS NOT NULL AND duration IS NOT NULL
        """)
        all_tracks = cursor.fetchall()

        # Filter out tracks already in MB groups to avoid double-reporting
        handled_ids = {t["id"] for group in groups for t in group.tracks}
        remaining_tracks = [t for t in all_tracks if t["id"] not in handled_ids]

        # Group by Artist + Title
        at_groups = defaultdict(list)
        for t in remaining_tracks:
            at_groups[(t["norm_artist"], t["norm_title"])].append(t)

        for (artist, title), tracks in at_groups.items():
            if len(tracks) > 1:
                # Sub-group by duration (+- 2 seconds)
                dur_groups: list[list[dict[str, Any]]] = []
                for t in tracks:
                    placed = False
                    for dg in dur_groups:
                        if abs(dg[0]["duration"] - t["duration"]) <= 2.0:
                            dg.append(t)
                            placed = True
                            break
                    if not placed:
                        dur_groups.append([t])

                for dg in dur_groups:
                    if len(dg) > 1:
                        keep_id = _determine_keep_track(dg)
                        groups.append(
                            DuplicateGroup(
                                group_id=f"text:{artist}:{title}",
                                reason="Artist, Title, and Duration match",
                                tracks=dg,
                                keep_track_id=keep_id,
                            )
                        )

    return groups


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
