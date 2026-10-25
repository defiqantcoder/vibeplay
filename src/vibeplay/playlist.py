"""Smart playlist generation engine based on vibe vectors, harmonic mixing, and constraints."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from vibeplay.config import Settings, get_settings
from vibeplay.db import (
    add_tracks_to_playlist,
    create_playlist,
    get_connection,
    get_tracks_with_features,
)
from vibeplay.vectors import compute_clusters, get_or_build_vibe_vectors

logger = logging.getLogger(__name__)

# Camelot Wheel pitch-class mappings (A = Minor, B = Major)
CAMELOT_MAJOR: dict[str, str] = {
    "B": "1B",
    "CB": "1B",
    "F#": "2B",
    "GB": "2B",
    "C#": "3B",
    "DB": "3B",
    "G#": "4B",
    "AB": "4B",
    "D#": "5B",
    "EB": "5B",
    "A#": "6B",
    "BB": "6B",
    "F": "7B",
    "C": "8B",
    "G": "9B",
    "D": "10B",
    "A": "11B",
    "E": "12B",
}

CAMELOT_MINOR: dict[str, str] = {
    "G#": "1A",
    "AB": "1A",
    "D#": "2A",
    "EB": "2A",
    "A#": "3A",
    "BB": "3A",
    "F": "4A",
    "C": "5A",
    "G": "6A",
    "D": "7A",
    "A": "8A",
    "E": "9A",
    "B": "10A",
    "CB": "10A",
    "F#": "11A",
    "GB": "11A",
    "C#": "12A",
    "DB": "12A",
}

VIBE_PRESETS: dict[str, dict[str, Any]] = {
    "chill": {
        "energy_max": 0.50,
        "mood_min": {"relaxed": 0.35},
        "danceability_max": 0.65,
    },
    "energetic": {
        "energy_min": 0.70,
        "bpm_min": 115.0,
    },
    "workout": {
        "energy_min": 0.70,
        "bpm_min": 115.0,
    },
    "melancholic": {
        "mood_min": {"sad": 0.35},
        "energy_max": 0.55,
    },
    "melancholy": {
        "mood_min": {"sad": 0.35},
        "energy_max": 0.55,
    },
    "euphoric": {
        "mood_min": {"happy": 0.35, "party": 0.30},
        "energy_min": 0.60,
    },
    "deep_focus": {
        "energy_max": 0.45,
        "danceability_max": 0.50,
        "mood_min": {"relaxed": 0.30},
    },
    "dark_intense": {
        "mood_min": {"aggressive": 0.35},
        "energy_min": 0.65,
    },
    "ambient": {
        "energy_max": 0.40,
        "danceability_max": 0.45,
        "mood_min": {"acoustic": 0.35},
    },
    "lofi": {
        "bpm_min": 70.0,
        "bpm_max": 95.0,
        "energy_max": 0.55,
        "mood_min": {"relaxed": 0.35},
    },
    "driving": {
        "bpm_min": 110.0,
        "bpm_max": 135.0,
        "energy_min": 0.60,
        "danceability_min": 0.55,
    },
    "party": {
        "energy_min": 0.60,
        "mood_min": {"party": 0.35},
        "danceability_min": 0.55,
    },
    "acoustic": {
        "mood_min": {"acoustic": 0.45},
        "energy_max": 0.65,
    },
    "electronic": {
        "mood_min": {"electronic": 0.45},
        "energy_min": 0.45,
    },
    "happy": {
        "mood_min": {"happy": 0.40},
        "energy_min": 0.50,
    },
}


def key_to_camelot(key: str | None, scale: str | None) -> str | None:
    """Map musical key and scale to standard Camelot Wheel notation.

    Args:
        key: Key name (e.g., 'C', 'C#', 'Am', 'Eb').
        scale: Scale name (e.g., 'major', 'minor').

    Returns:
        str | None: Camelot notation (e.g., '8B', '8A') or None if unknown.
    """
    if not key or not str(key).strip():
        return None

    raw_key = str(key).strip()
    raw_scale = str(scale).strip().lower() if scale else ""

    # Parse compound formats like 'Am', 'C#m', 'C minor'
    if raw_key.endswith("m") and not raw_key.endswith("maj") and not raw_key.endswith("major") and len(raw_key) > 1:
        raw_scale = "minor"
        raw_key = raw_key[:-1]
    elif raw_key.lower().endswith(" minor") or raw_key.lower().endswith(" min"):
        raw_scale = "minor"
        raw_key = raw_key.rsplit(" ", 1)[0]
    elif raw_key.lower().endswith(" major") or raw_key.lower().endswith(" maj"):
        raw_scale = "major"
        raw_key = raw_key.rsplit(" ", 1)[0]

    normalized_key = raw_key.upper().replace("♯", "#").replace("♭", "B")
    if not normalized_key:
        return None

    if raw_scale == "minor":
        return CAMELOT_MINOR.get(normalized_key)
    return CAMELOT_MAJOR.get(normalized_key)


def camelot_distance(code1: str, code2: str) -> int:
    """Calculate circular distance between two Camelot wheel keys.

    Args:
        code1: First Camelot code (e.g. '8B').
        code2: Second Camelot code (e.g. '9B' or '8A').

    Returns:
        int: Number of harmonic steps separating the keys.
    """
    try:
        num1, mode1 = int(code1[:-1]), code1[-1].upper()
        num2, mode2 = int(code2[:-1]), code2[-1].upper()
    except (ValueError, IndexError):
        return 6

    diff = abs(num1 - num2)
    circle_dist = min(diff, 12 - diff)

    if mode1 == mode2:
        return circle_dist
    # Crossing between major and minor: relative keys (distance 0) count as 1 step
    return circle_dist + 1


def camelot_key_score(code1: str | None, code2: str | None) -> float:
    """Compute harmonic compatibility score between two Camelot wheel positions.

    Args:
        code1: First Camelot code.
        code2: Second Camelot code.

    Returns:
        float: Compatibility score between 0.2 and 1.0.
    """
    if not code1 or not code2:
        return 0.7  # Neutral score when key is missing/unknown

    dist = camelot_distance(code1, code2)
    if dist == 0:
        return 1.0  # Exact key match
    elif dist == 1:
        return 0.95  # Consonant / relative key or +-1 step
    elif dist == 2:
        return 0.70  # Whole step / energy shift
    elif dist == 3:
        return 0.50  # Moderate leap
    return 0.20  # Dissonant leap


def fold_bpm(bpm: float | None) -> float:
    """Fold BPM into standard DJ reference octave [80.0, 160.0).

    Args:
        bpm: Raw track tempo in BPM.

    Returns:
        float: Octave-folded tempo.
    """
    if bpm is None or bpm <= 0:
        return 120.0
    val = float(bpm)
    while val < 80.0:
        val *= 2.0
    while val >= 160.0:
        val /= 2.0
    return val


def bpm_transition_score(bpm1: float | None, bpm2: float | None) -> float:
    """Calculate transition smoothness score between two tempos using octave folding.

    Args:
        bpm1: Tempo of starting track.
        bpm2: Tempo of incoming track.

    Returns:
        float: Transition score in [0.0, 1.0].
    """
    if bpm1 is None or bpm2 is None or bpm1 <= 0 or bpm2 <= 0:
        return 0.7
    f1 = fold_bpm(bpm1)
    f2 = fold_bpm(bpm2)
    diff = abs(f1 - f2)
    return max(0.0, 1.0 - (diff / 30.0))


@dataclass
class TrackTransition:
    """Detailed transition scores between adjacent tracks in a playlist."""

    from_track_id: int | None
    to_track_id: int
    vibe_similarity: float
    bpm_score: float
    key_score: float
    total_score: float
    harmonic_label: str | None = None
    harmonic_badge: str | None = None
    harmonic_type: str | None = None
    bpm_delta: float | None = None
    bpm_delta_pct: float | None = None
    quality: str | None = None
    badge_class: str | None = None
    clash_level: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert transition to dictionary representation."""
        return asdict(self)


def evaluate_harmonic_transition(
    from_key: str | None = None,
    from_scale: str | None = None,
    to_key: str | None = None,
    to_scale: str | None = None,
    from_bpm: float | None = None,
    to_bpm: float | None = None,
    from_camelot: str | None = None,
    to_camelot: str | None = None,
) -> dict[str, Any]:
    """Evaluate harmonic compatibility and tempo transition between two tracks.

    Handles Camelot wheel notation ([1-12][A-B]), detecting exact harmonic matches,
    relative major/minor matches, +1 energy boosts, -1 energy drops, and harmonic clashes.
    Also calculates folded tempo delta and provides color-coded badge classes.
    """
    c1 = (from_camelot or key_to_camelot(from_key, from_scale) or "").strip().upper()
    c2 = (to_camelot or key_to_camelot(to_key, to_scale) or "").strip().upper()

    # Camelot Evaluation
    if not c1 or not c2 or len(c1) < 2 or len(c2) < 2:
        harmonic_type = "unknown"
        relation_label = "Neutral / Key Unknown"
        harmonic_badge = "neutral"
        harmonic_score = 70.0
        clash_level = 0
    else:
        try:
            n1, m1 = int(c1[:-1]), c1[-1]
            n2, m2 = int(c2[:-1]), c2[-1]
        except (ValueError, IndexError):
            n1, m1, n2, m2 = 0, "", 0, ""

        if n1 <= 0 or n1 > 12 or n2 <= 0 or n2 > 12 or m1 not in ("A", "B") or m2 not in ("A", "B"):
            harmonic_type = "unknown"
            relation_label = "Neutral / Key Unknown"
            harmonic_badge = "neutral"
            harmonic_score = 70.0
            clash_level = 0
        elif n1 == n2 and m1 == m2:
            harmonic_type = "exact"
            relation_label = f"{c1} -> {c2} [Exact Harmonic Match]"
            harmonic_badge = "seamless"
            harmonic_score = 100.0
            clash_level = 0
        elif n1 == n2 and m1 != m2:
            harmonic_type = "relative"
            relation_label = f"{c1} -> {c2} [Exact Harmonic Match]"
            harmonic_badge = "seamless"
            harmonic_score = 95.0
            clash_level = 0
        elif m1 == m2 and (n2 - n1) % 12 == 1:
            harmonic_type = "boost"
            relation_label = f"{c1} -> {c2} [+1 Energy Boost]"
            harmonic_badge = "harmonic-boost"
            harmonic_score = 90.0
            clash_level = 0
        elif m1 == m2 and (n1 - n2) % 12 == 1:
            harmonic_type = "drop"
            relation_label = f"{c1} -> {c2} [-1 Energy Drop]"
            harmonic_badge = "acceptable"
            harmonic_score = 85.0
            clash_level = 0
        elif m1 != m2 and ((n2 - n1) % 12 == 1 or (n1 - n2) % 12 == 1):
            harmonic_type = "pivot"
            relation_label = f"{c1} -> {c2} [Diagonal Mode Shift ±1]"
            harmonic_badge = "acceptable"
            harmonic_score = 75.0
            clash_level = 1
        else:
            fwd = (n2 - n1) % 12
            bwd = (n1 - n2) % 12
            if fwd <= 6:
                sign = "+"
                steps = fwd
            else:
                sign = "-"
                steps = bwd

            harmonic_type = "clash"
            relation_label = f"{c1} -> {c2} [Harmonic Clash {sign}{steps}]"
            harmonic_badge = "clash"
            harmonic_score = max(20.0, 60.0 - steps * 8.0)
            clash_level = 2

    # BPM Evaluation
    if from_bpm is not None and to_bpm is not None and from_bpm > 0 and to_bpm > 0:
        f1 = fold_bpm(from_bpm)
        f2 = fold_bpm(to_bpm)
        bpm_diff = round(abs(f2 - f1), 1)
        bpm_pct = round(abs(f2 - f1) / f1 * 100.0, 1) if f1 > 0 else 0.0

        if bpm_pct <= 1.5:
            bpm_status = "Smooth Lock"
            bpm_badge = "score-high"
        elif bpm_pct <= 4.0:
            bpm_status = "Mixable"
            bpm_badge = "score-high"
        elif bpm_pct <= 8.0:
            bpm_status = "Moderate Shift"
            bpm_badge = "score-mid"
        else:
            bpm_status = "Tempo Jump"
            bpm_badge = "score-low"

        bpm_score = max(0.0, 100.0 - (bpm_diff / 30.0) * 100.0)
    else:
        bpm_diff = 0.0
        bpm_pct = 0.0
        bpm_status = "BPM Neutral"
        bpm_badge = "score-mid"
        bpm_score = 70.0

    total_score = round(0.60 * harmonic_score + 0.40 * bpm_score, 1)

    if total_score >= 85.0:
        overall_quality = "Seamless"
        overall_badge_class = "score-high"
    elif total_score >= 70.0:
        overall_quality = "Harmonic"
        overall_badge_class = "score-high"
    elif total_score >= 50.0:
        overall_quality = "Acceptable"
        overall_badge_class = "score-mid"
    else:
        overall_quality = "Harmonic Clash"
        overall_badge_class = "score-low"

    return {
        "from_camelot": c1 or None,
        "to_camelot": c2 or None,
        "from_key": from_key,
        "to_key": to_key,
        "from_scale": from_scale,
        "to_scale": to_scale,
        "harmonic_type": harmonic_type,
        "relation_label": relation_label,
        "harmonic_badge": harmonic_badge,
        "harmonic_score": round(harmonic_score, 1),
        "from_bpm": from_bpm,
        "to_bpm": to_bpm,
        "bpm_delta": bpm_diff,
        "bpm_delta_pct": bpm_pct,
        "bpm_status": bpm_status,
        "bpm_badge": bpm_badge,
        "bpm_score": round(bpm_score, 1),
        "total_score": total_score,
        "normalized_score": round(total_score / 100.0, 4),
        "quality": overall_quality,
        "badge_class": overall_badge_class,
        "clash_level": clash_level,
    }


def calculate_transition_metrics(
    tracks: list[dict[str, Any]] | list[PlaylistTrackItem],
) -> list[dict[str, Any]]:
    """Compute rich harmonic and tempo transition details between consecutive tracks."""
    transitions: list[dict[str, Any]] = []
    if len(tracks) < 2:
        return transitions

    for idx in range(len(tracks) - 1):
        t1 = tracks[idx]
        t2 = tracks[idx + 1]

        def _get(obj: Any, key: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        k1, s1 = _get(t1, "key"), _get(t1, "scale")
        k2, s2 = _get(t2, "key"), _get(t2, "scale")
        c1 = _get(t1, "camelot") or key_to_camelot(k1, s1)
        c2 = _get(t2, "camelot") or key_to_camelot(k2, s2)
        bpm1 = _get(t1, "bpm")
        bpm2 = _get(t2, "bpm")

        eval_result = evaluate_harmonic_transition(
            from_key=k1,
            from_scale=s1,
            to_key=k2,
            to_scale=s2,
            from_bpm=bpm1,
            to_bpm=bpm2,
            from_camelot=c1,
            to_camelot=c2,
        )

        item = {
            "from_index": idx + 1,
            "to_index": idx + 2,
            "from_track_id": _get(t1, "track_id"),
            "to_track_id": _get(t2, "track_id"),
            "from_title": _get(t1, "title") or "Unknown Title",
            "to_title": _get(t2, "title") or "Unknown Title",
            "from_artist": _get(t1, "artist") or "Unknown Artist",
            "to_artist": _get(t2, "artist") or "Unknown Artist",
            **eval_result,
        }
        transitions.append(item)

    return transitions


def calculate_playlist_summary(
    tracks: list[Any],
    transitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate aggregate telemetry metrics for a sequenced playlist."""
    if transitions is None:
        transitions = calculate_transition_metrics(tracks)

    def _get_dur(t: Any) -> float:
        if isinstance(t, dict):
            return float(t.get("duration") or 0.0)
        return float(getattr(t, "duration", 0.0) or 0.0)

    total_dur = sum(_get_dur(t) for t in tracks)
    scores = [tr["total_score"] for tr in transitions]
    avg_score = round(float(np.mean(scores)), 1) if scores else 100.0

    seamless_cnt = sum(1 for tr in transitions if tr.get("harmonic_badge") == "seamless")
    boost_cnt = sum(1 for tr in transitions if tr.get("harmonic_badge") == "harmonic-boost")
    acceptable_cnt = sum(1 for tr in transitions if tr.get("harmonic_badge") == "acceptable")
    clash_cnt = sum(1 for tr in transitions if tr.get("harmonic_badge") == "clash")

    return {
        "track_count": len(tracks),
        "total_duration": total_dur,
        "total_duration_formatted": f"{int(total_dur // 60)}m {int(total_dur % 60):02d}s",
        "avg_transition_score": avg_score,
        "normalized_avg_score": round(avg_score / 100.0, 2),
        "seamless_count": seamless_cnt,
        "boost_count": boost_cnt,
        "acceptable_count": acceptable_cnt,
        "clash_count": clash_cnt,
    }


@dataclass
class PlaylistTrackItem:
    """A track entry within a sequenced playlist."""

    position: int
    track_id: int
    title: str
    artist: str
    album: str
    duration: float
    bpm: float | None
    key: str | None
    scale: str | None
    camelot: str | None
    energy: float | None
    danceability: float | None
    path: str
    transition: TrackTransition | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert item to dictionary representation."""
        data = asdict(self)
        if self.transition:
            data["transition"] = self.transition.to_dict()
        return data


@dataclass
class GeneratedPlaylist:
    """Complete container for a generated and sequenced playlist."""

    playlist_id: int
    name: str
    description: str | None
    mode: str
    tracks: list[PlaylistTrackItem]
    total_duration: float
    avg_transition_score: float

    def to_dict(self) -> dict[str, Any]:
        """Convert playlist to dictionary representation."""
        return {
            "playlist_id": self.playlist_id,
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "total_duration": self.total_duration,
            "avg_transition_score": self.avg_transition_score,
            "track_count": len(self.tracks),
            "tracks": [t.to_dict() for t in self.tracks],
        }


class PlaylistRuleConfig(BaseModel):
    """Specification model for rule-based and arc-guided playlist generation."""

    mode: str = "seed"
    seed_track_ids: list[int] = Field(default_factory=list)
    cluster_id: int | None = None
    arc: str | None = None
    vibe: str | None = None
    bpm_min: float | None = None
    bpm_max: float | None = None
    max_bpm_delta: float | None = None
    key: str | None = None
    scale: str | None = None
    mood_min: dict[str, float] = Field(default_factory=dict)
    energy_min: float | None = None
    energy_max: float | None = None
    danceability_min: float | None = None
    danceability_max: float | None = None
    year_min: int | None = None
    year_max: int | None = None
    genre_include: list[str] = Field(default_factory=list)
    genre_exclude: list[str] = Field(default_factory=list)
    limit: int = 25
    minutes: float | None = None
    max_artist_tracks: int = 2


def evaluate_energy_arc(arc_name: str, step: int, total_steps: int) -> float:
    """Calculate target energy value at a normalized position along an energy arc.

    Args:
        arc_name: Arc identifier ('ramp_up', 'energy_ramp', 'peak', 'peak_hour_wave',
            'steady', 'steady_pulse', 'late_night_chill', 'cooldown').
        step: 0-indexed step in the playlist sequence.
        total_steps: Total target track count.

    Returns:
        float: Expected energy value in [0.0, 1.0].
    """
    if total_steps <= 1:
        t = 0.5
    else:
        t = step / (total_steps - 1)

    clean_arc = arc_name.lower().strip().replace("-", "_")
    if clean_arc in ("ramp_up", "ramp", "energy_ramp"):
        return 0.25 + 0.65 * t
    elif clean_arc in ("cooldown", "cool_down"):
        return 0.85 - 0.60 * t
    elif clean_arc in ("peak", "warmup_peak_cooldown", "wave", "peak_hour_wave", "peak_wave"):
        return 0.35 + 0.55 * math.sin(math.pi * t)
    elif clean_arc in ("steady", "plateau", "steady_pulse"):
        return 0.60
    elif clean_arc in ("late_night_chill", "night_chill", "chill", "late_night"):
        return max(0.20, 0.45 - 0.25 * t)
    logger.warning("Unrecognized arc '%s'; using steady arc (0.60)", arc_name)
    return 0.60


def calculate_transition(
    from_meta: dict[str, Any] | None,
    to_meta: dict[str, Any],
    from_vector: np.ndarray | None = None,
    to_vector: np.ndarray | None = None,
) -> TrackTransition:
    """Calculate transition smoothness scores between two tracks.

    Args:
        from_meta: Metadata dictionary of originating track.
        to_meta: Metadata dictionary of destination track.
        from_vector: Vibe vector of originating track.
        to_vector: Vibe vector of destination track.

    Returns:
        TrackTransition: Populated transition metrics.
    """
    to_id = int(to_meta["track_id"])
    if from_meta is None or from_vector is None or to_vector is None:
        return TrackTransition(
            from_track_id=None,
            to_track_id=to_id,
            vibe_similarity=1.0,
            bpm_score=1.0,
            key_score=1.0,
            total_score=1.0,
            harmonic_label="Start Track",
            harmonic_badge="neutral",
            harmonic_type="start",
            quality="Start",
            badge_class="score-high",
            clash_level=0,
        )

    # Cosine similarity over unit-normalized vibe vectors
    dot = float(np.dot(from_vector, to_vector))
    vibe_sim = float(np.clip(dot, 0.0, 1.0))

    bpm_score = bpm_transition_score(from_meta.get("bpm"), to_meta.get("bpm"))

    c1 = key_to_camelot(from_meta.get("key"), from_meta.get("scale"))
    c2 = key_to_camelot(to_meta.get("key"), to_meta.get("scale"))
    key_score = camelot_key_score(c1, c2)

    total_score = 0.45 * vibe_sim + 0.30 * bpm_score + 0.25 * key_score

    eval_harm = evaluate_harmonic_transition(
        from_key=from_meta.get("key"),
        from_scale=from_meta.get("scale"),
        to_key=to_meta.get("key"),
        to_scale=to_meta.get("scale"),
        from_bpm=from_meta.get("bpm"),
        to_bpm=to_meta.get("bpm"),
        from_camelot=c1,
        to_camelot=c2,
    )

    return TrackTransition(
        from_track_id=int(from_meta["track_id"]),
        to_track_id=to_id,
        vibe_similarity=round(vibe_sim, 4),
        bpm_score=round(bpm_score, 4),
        key_score=round(key_score, 4),
        total_score=round(total_score, 4),
        harmonic_label=eval_harm["relation_label"],
        harmonic_badge=eval_harm["harmonic_badge"],
        harmonic_type=eval_harm["harmonic_type"],
        bpm_delta=eval_harm["bpm_delta"],
        bpm_delta_pct=eval_harm["bpm_delta_pct"],
        quality=eval_harm["quality"],
        badge_class=eval_harm["badge_class"],
        clash_level=eval_harm["clash_level"],
    )


def _get_dedup_key(meta: dict[str, Any]) -> str:
    """Generate a deduplication key to eliminate duplicate song recordings."""
    mb_rec = meta.get("mb_recording_id")
    if mb_rec and str(mb_rec).strip():
        return f"mb:{str(mb_rec).strip().lower()}"
    artist = (meta.get("artist") or "").strip().lower()
    title = (meta.get("title") or "").strip().lower()
    return f"raw:{artist}:{title}"


def generate_playlist(
    db_path: Path,
    name: str = "Vibe Playlist",
    seed_track_id: int | None = None,
    seed_track_ids: list[int] | None = None,
    cluster_id: int | None = None,
    vibe: str | None = None,
    arc: str | None = None,
    limit: int = 25,
    minutes: float | None = None,
    max_artist_tracks: int = 2,
    rules: PlaylistRuleConfig | None = None,
    description: str | None = None,
    settings: Settings | None = None,
) -> GeneratedPlaylist:
    """Generate a cohesive playlist matching target vibe parameters and constraints.

    Supports seed similarity, cluster extraction, rule-based filtering, and energy arcs.
    Enforces maximum artist count, recording deduplication, and transition optimization.

    Args:
        db_path: Path to SQLite database.
        name: Name for the playlist.
        seed_track_id: Single starting/seed track ID.
        seed_track_ids: Multiple seed track IDs.
        cluster_id: Target cluster ID to turn into a playlist.
        vibe: Optional textual or preset descriptor of the vibe.
        arc: Optional trajectory name (e.g. 'ramp_up', 'cooldown', 'peak', 'steady').
        limit: Maximum number of tracks in the playlist.
        minutes: Target total duration in minutes.
        max_artist_tracks: Maximum tracks allowed by any single artist.
        rules: Optional structured rule configuration.
        settings: Application settings.

    Returns:
        GeneratedPlaylist: Sequenced playlist saved to the database.

    Raises:
        ValueError: If no analyzed tracks exist or required seed/cluster is missing.
    """
    cfg = settings or get_settings()

    # Consolidate configuration
    active_seeds: list[int] = []
    if seed_track_ids:
        active_seeds.extend(seed_track_ids)
    if seed_track_id is not None and seed_track_id not in active_seeds:
        active_seeds.insert(0, seed_track_id)

    if rules is not None:
        mode = rules.mode
        active_seeds = active_seeds or rules.seed_track_ids
        cluster_id = cluster_id if cluster_id is not None else rules.cluster_id
        vibe = vibe or rules.vibe
        arc = arc or rules.arc
        limit = rules.limit or limit
        minutes = rules.minutes or minutes
        max_artist_tracks = rules.max_artist_tracks or max_artist_tracks
    else:
        if active_seeds:
            mode = "seed"
        elif cluster_id is not None:
            mode = "cluster"
        elif arc is not None:
            mode = "arc"
        elif vibe is not None:
            mode = "rules"
        else:
            mode = "seed"

    config_rules = PlaylistRuleConfig(
        mode=mode,
        seed_track_ids=active_seeds,
        cluster_id=cluster_id,
        arc=arc,
        vibe=vibe,
        limit=limit,
        minutes=minutes,
        max_artist_tracks=max_artist_tracks,
    )
    if rules:
        config_rules.bpm_min = rules.bpm_min
        config_rules.bpm_max = rules.bpm_max
        config_rules.key = rules.key
        config_rules.scale = rules.scale
        config_rules.mood_min = rules.mood_min
        config_rules.energy_min = rules.energy_min
        config_rules.energy_max = rules.energy_max
        config_rules.danceability_min = rules.danceability_min
        config_rules.danceability_max = rules.danceability_max
        config_rules.year_min = rules.year_min
        config_rules.year_max = rules.year_max
        config_rules.genre_include = rules.genre_include
        config_rules.genre_exclude = rules.genre_exclude

    # Load vectors and metadata
    track_ids, vectors, meta_map = get_or_build_vibe_vectors(db_path=db_path, settings=cfg)
    if len(track_ids) == 0:
        raise ValueError("Cannot generate playlist: no analyzed audio tracks found in library.")

    # Apply vibe preset filters if vibe is specified
    if config_rules.vibe:
        vibe_key = config_rules.vibe.lower().strip()
        if vibe_key in VIBE_PRESETS:
            preset = VIBE_PRESETS[vibe_key]
            if "energy_min" in preset and config_rules.energy_min is None:
                config_rules.energy_min = preset["energy_min"]
            if "energy_max" in preset and config_rules.energy_max is None:
                config_rules.energy_max = preset["energy_max"]
            if "danceability_min" in preset and config_rules.danceability_min is None:
                config_rules.danceability_min = preset["danceability_min"]
            if "danceability_max" in preset and config_rules.danceability_max is None:
                config_rules.danceability_max = preset["danceability_max"]
            if "bpm_min" in preset and config_rules.bpm_min is None:
                config_rules.bpm_min = preset["bpm_min"]
            if "mood_min" in preset:
                for mk, mv in preset["mood_min"].items():
                    if mk not in config_rules.mood_min:
                        config_rules.mood_min[mk] = mv

    # Fetch rich track data from DB
    with get_connection(db_path) as conn:
        all_tracks_rows = get_tracks_with_features(conn)

    rich_tracks_by_id: dict[int, dict[str, Any]] = {}
    for r in all_tracks_rows:
        tid = int(r["track_id"])
        rich_tracks_by_id[tid] = {
            "track_id": tid,
            "path": r["path"],
            "title": r["title"] or "Unknown Title",
            "artist": r["artist"] or "Unknown Artist",
            "album_artist": r["album_artist"] or r["artist"] or "Unknown Artist",
            "album": r["album"] or "Unknown Album",
            "year": r["year"],
            "genre": r["genre"],
            "duration": float(r["duration"]) if r["duration"] is not None else 180.0,
            "mb_recording_id": r["mb_recording_id"],
            "enriched_genres": r["enriched_genres"],
            "enriched_tags": r["enriched_tags"],
            "bpm": float(r["bpm"]) if r["bpm"] is not None else 120.0,
            "key": r["key"],
            "scale": r["scale"],
            "energy": float(r["energy"]) if r["energy"] is not None else 0.5,
            "danceability": float(r["danceability"]) if r["danceability"] is not None else 0.5,
            "loudness": float(r["loudness"]) if r["loudness"] is not None else -10.0,
            "mood_scores": json.loads(r["mood_scores"]) if r["mood_scores"] else {},
        }

    id_to_vec_idx = {int(tid): idx for idx, tid in enumerate(track_ids)}

    # Candidate Filtering based on mode
    candidate_ids: set[int] = set()

    if mode == "cluster":
        clust_res = compute_clusters(db_path=db_path, settings=cfg)
        chosen_cluster = None
        target_cid = cluster_id if cluster_id is not None else 0
        for c in clust_res.clusters:
            if c.cluster_id == target_cid:
                chosen_cluster = c
                break
        if chosen_cluster:
            candidate_ids = set(chosen_cluster.track_ids)
            logger.info("Filtered to %d tracks in cluster %d", len(candidate_ids), target_cid)
        else:
            logger.warning("Cluster %d not found; using all library tracks", target_cid)
            candidate_ids = set(rich_tracks_by_id.keys())
    else:
        # Filter candidate pool with rule criteria
        for tid, meta in rich_tracks_by_id.items():
            if tid not in id_to_vec_idx:
                continue

            # Tempo bounds
            bpm = meta.get("bpm")
            if config_rules.bpm_min is not None and bpm is not None and bpm < config_rules.bpm_min:
                continue
            if config_rules.bpm_max is not None and bpm is not None and bpm > config_rules.bpm_max:
                continue

            # Energy bounds
            energy = meta.get("energy")
            if config_rules.energy_min is not None and energy is not None and energy < config_rules.energy_min:
                continue
            if config_rules.energy_max is not None and energy is not None and energy > config_rules.energy_max:
                continue

            # Danceability bounds
            dance = meta.get("danceability")
            if config_rules.danceability_min is not None and dance is not None and dance < config_rules.danceability_min:
                continue
            if config_rules.danceability_max is not None and dance is not None and dance > config_rules.danceability_max:
                continue

            # Year bounds
            year = meta.get("year")
            if config_rules.year_min is not None and year is not None and year < config_rules.year_min:
                continue
            if config_rules.year_max is not None and year is not None and year > config_rules.year_max:
                continue

            # Genre include / exclude
            combined_genre_text = (f"{meta.get('genre') or ''} {meta.get('enriched_genres') or ''} {meta.get('enriched_tags') or ''}").lower()
            if config_rules.genre_include:
                if not any(gi.lower() in combined_genre_text for gi in config_rules.genre_include):
                    continue
            if config_rules.genre_exclude:
                if any(ge.lower() in combined_genre_text for ge in config_rules.genre_exclude):
                    continue

            # Mood minimums
            mood_scores = meta.get("mood_scores") or {}
            mood_mismatch = False
            for mk, mv in config_rules.mood_min.items():
                if float(mood_scores.get(mk, 0.0)) < mv:
                    mood_mismatch = True
                    break
            if mood_mismatch:
                continue

            # Key / Scale
            if config_rules.key is not None:
                req_camelot = key_to_camelot(config_rules.key, config_rules.scale)
                trk_camelot = key_to_camelot(meta.get("key"), meta.get("scale"))
                if req_camelot and trk_camelot and req_camelot != trk_camelot:
                    continue

            candidate_ids.add(tid)

    # Fallback if filters were too restrictive
    if len(candidate_ids) == 0:
        logger.warning("Rules yielded 0 candidates; falling back to full library tracks.")
        candidate_ids = set(rich_tracks_by_id.keys())

    # Build reference vibe vector
    if active_seeds:
        seed_vectors = [vectors[id_to_vec_idx[s]] for s in active_seeds if s in id_to_vec_idx]
        if seed_vectors:
            ref_vector = np.mean(seed_vectors, axis=0)
            norm = np.linalg.norm(ref_vector)
            if norm > 0:
                ref_vector = ref_vector / norm
        else:
            ref_vector = vectors[0]
    else:
        # Average vector across candidates
        cand_indices = [id_to_vec_idx[cid] for cid in candidate_ids if cid in id_to_vec_idx]
        if cand_indices:
            ref_vector = np.mean(vectors[cand_indices], axis=0)
            norm = np.linalg.norm(ref_vector)
            ref_vector = (ref_vector / norm) if norm > 0 else vectors[0]
        else:
            ref_vector = vectors[0]

    # Select Starting Track
    start_track_id: int | None = None
    if active_seeds and active_seeds[0] in rich_tracks_by_id:
        start_track_id = active_seeds[0]
    elif config_rules.arc:
        # Pick track closest to starting arc energy
        target_start_energy = evaluate_energy_arc(config_rules.arc, 0, limit)
        best_diff = float("inf")
        for cid in candidate_ids:
            e = rich_tracks_by_id[cid].get("energy", 0.5)
            diff = abs(e - target_start_energy)
            if diff < best_diff:
                best_diff = diff
                start_track_id = cid
    else:
        # Track most similar to reference vector
        best_sim = -float("inf")
        for cid in candidate_ids:
            vec_idx = id_to_vec_idx[cid]
            sim = float(np.dot(vectors[vec_idx], ref_vector))
            if sim > best_sim:
                best_sim = sim
                start_track_id = cid

    if start_track_id is None:
        start_track_id = next(iter(candidate_ids))

    # Sequencing Loop
    playlist_items: list[PlaylistTrackItem] = []
    used_track_ids: set[int] = set()
    used_dedup_keys: set[str] = set()
    artist_counts: dict[str, int] = {}
    current_duration: float = 0.0
    target_duration_seconds = (minutes * 60.0) if minutes is not None else None

    # Add starting track
    curr_id = start_track_id
    curr_meta = rich_tracks_by_id[curr_id]
    curr_vec = vectors[id_to_vec_idx[curr_id]]
    curr_artist = curr_meta.get("artist") or "Unknown Artist"

    init_trans = calculate_transition(None, curr_meta, None, curr_vec)
    playlist_items.append(
        PlaylistTrackItem(
            position=1,
            track_id=curr_id,
            title=curr_meta["title"],
            artist=curr_meta["artist"],
            album=curr_meta["album"],
            duration=curr_meta["duration"],
            bpm=curr_meta["bpm"],
            key=curr_meta["key"],
            scale=curr_meta["scale"],
            camelot=key_to_camelot(curr_meta["key"], curr_meta["scale"]),
            energy=curr_meta["energy"],
            danceability=curr_meta["danceability"],
            path=curr_meta["path"],
            transition=init_trans,
        )
    )
    used_track_ids.add(curr_id)
    used_dedup_keys.add(_get_dedup_key(curr_meta))
    artist_counts[curr_artist] = 1
    current_duration += curr_meta["duration"]

    # Greedy sequencing for remaining slots
    while len(playlist_items) < limit:
        if target_duration_seconds is not None and current_duration >= target_duration_seconds:
            break

        prev_meta = curr_meta
        prev_vec = curr_vec
        step_idx = len(playlist_items)

        # Filter remaining candidates by deduplication
        available_cids = [cid for cid in candidate_ids if cid not in used_track_ids and _get_dedup_key(rich_tracks_by_id[cid]) not in used_dedup_keys]
        if not available_cids:
            break

        # Filter by artist count constraint
        eligible_cids = [
            cid for cid in available_cids if artist_counts.get(rich_tracks_by_id[cid].get("artist") or "Unknown Artist", 0) < max_artist_tracks
        ]
        pool = eligible_cids if eligible_cids else available_cids

        # Score candidates
        best_candidate_id: int | None = None
        best_candidate_score = -float("inf")
        best_candidate_trans: TrackTransition | None = None

        target_arc_energy = evaluate_energy_arc(config_rules.arc, step_idx, limit) if config_rules.arc else None

        for cid in pool:
            cand_meta = rich_tracks_by_id[cid]
            cand_vec = vectors[id_to_vec_idx[cid]]

            # Transition smoothness score
            trans = calculate_transition(prev_meta, cand_meta, prev_vec, cand_vec)

            # Vibe alignment with overall reference
            theme_sim = float(np.clip(float(np.dot(cand_vec, ref_vector)), 0.0, 1.0))

            if target_arc_energy is not None:
                cand_energy = cand_meta.get("energy", 0.5)
                arc_score = max(0.0, 1.0 - abs(cand_energy - target_arc_energy) * 1.5)
                score = 0.45 * trans.total_score + 0.25 * theme_sim + 0.30 * arc_score
            else:
                score = 0.60 * trans.total_score + 0.40 * theme_sim

            if config_rules.max_bpm_delta is not None and prev_meta.get("bpm") and cand_meta.get("bpm"):
                b_diff = abs(fold_bpm(prev_meta["bpm"]) - fold_bpm(cand_meta["bpm"]))
                if b_diff > config_rules.max_bpm_delta:
                    penalty = (b_diff - config_rules.max_bpm_delta) / 20.0
                    score -= min(0.40, penalty)

            if score > best_candidate_score:
                best_candidate_score = score
                best_candidate_id = cid
                best_candidate_trans = trans

        if best_candidate_id is None:
            break

        curr_id = best_candidate_id
        curr_meta = rich_tracks_by_id[curr_id]
        curr_vec = vectors[id_to_vec_idx[curr_id]]
        curr_artist = curr_meta.get("artist") or "Unknown Artist"

        pos = len(playlist_items) + 1
        playlist_items.append(
            PlaylistTrackItem(
                position=pos,
                track_id=curr_id,
                title=curr_meta["title"],
                artist=curr_meta["artist"],
                album=curr_meta["album"],
                duration=curr_meta["duration"],
                bpm=curr_meta["bpm"],
                key=curr_meta["key"],
                scale=curr_meta["scale"],
                camelot=key_to_camelot(curr_meta["key"], curr_meta["scale"]),
                energy=curr_meta["energy"],
                danceability=curr_meta["danceability"],
                path=curr_meta["path"],
                transition=best_candidate_trans,
            )
        )
        used_track_ids.add(curr_id)
        used_dedup_keys.add(_get_dedup_key(curr_meta))
        artist_counts[curr_artist] = artist_counts.get(curr_artist, 0) + 1
        current_duration += curr_meta["duration"]

    # Calculate average transition score
    transitions = [item.transition.total_score for item in playlist_items if item.transition]
    avg_trans_score = float(np.mean(transitions)) if transitions else 1.0

    # Persist to database
    desc = description or f"Generated by vibeplay ({mode} mode, {len(playlist_items)} tracks)"
    rules_json = config_rules.model_dump_json()

    with get_connection(db_path) as conn:
        playlist_id = create_playlist(
            conn=conn,
            name=name,
            description=desc,
            rules_json=rules_json,
        )
        add_tracks_to_playlist(
            conn=conn,
            playlist_id=playlist_id,
            track_ids=[item.track_id for item in playlist_items],
        )

    logger.info(
        "Saved playlist '%s' (ID %d) with %d tracks (duration=%.1f min, avg_score=%.2f)",
        name,
        playlist_id,
        len(playlist_items),
        current_duration / 60.0,
        avg_trans_score,
    )

    return GeneratedPlaylist(
        playlist_id=playlist_id,
        name=name,
        description=desc,
        mode=mode,
        tracks=playlist_items,
        total_duration=round(current_duration, 2),
        avg_transition_score=round(avg_trans_score, 4),
    )
