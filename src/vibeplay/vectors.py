"""Vibe vector formulation, feature normalization, and clustering module."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from vibeplay.config import Settings, get_settings
from vibeplay.db import get_connection, get_features_checksum, get_tracks_with_features

logger = logging.getLogger(__name__)

MOOD_KEYS: tuple[str, ...] = (
    "happy",
    "sad",
    "relaxed",
    "aggressive",
    "party",
    "acoustic",
    "electronic",
)


@dataclass
class SimilarTrack:
    """Represents a track matched by nearest-neighbor cosine similarity."""

    track_id: int
    similarity: float
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    bpm: float | None = None
    path: str | None = None

    def __iter__(self):
        """Allow tuple unpacking as (track_id, similarity)."""
        yield self.track_id
        yield self.similarity


@dataclass
class ClusterSummary:
    """Summary metrics and representative tracks for a vibe cluster."""

    cluster_id: int
    label: str
    size: int
    avg_bpm: float
    dominant_moods: list[tuple[str, float]]
    top_artists: list[tuple[str, int]]
    representative_tracks: list[dict[str, Any]]
    track_ids: list[int] = field(default_factory=list)


@dataclass
class ClusteringResult:
    """Complete results of an unsupervised clustering execution."""

    algorithm: str
    k: int
    total_tracks: int
    clusters: list[ClusterSummary]


def _compute_config_signature(settings: Settings) -> str:
    """Generate a hash signature for vector weighting and reduction parameters.

    Args:
        settings: Active application configuration settings.

    Returns:
        str: MD5 hex digest of the configuration parameters.
    """
    params_str = (
        f"bpm={settings.weight_bpm}:"
        f"loud={settings.weight_loudness}:"
        f"dance={settings.weight_danceability}:"
        f"energy={settings.weight_energy}:"
        f"mood={settings.weight_mood}:"
        f"emb={settings.weight_embedding}:"
        f"harm={settings.bpm_harmonic_weight}:"
        f"pca={settings.pca_embedding_dimensions}"
    )
    return hashlib.md5(params_str.encode("utf-8")).hexdigest()


def build_vibe_vectors(
    tracks_data: list[Any],
    settings: Settings | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[int, dict[str, Any]]]:
    """Assemble normalized vibe vectors from track feature records.

    Performs:
    1. BPM decomposition: Circular harmonic angle (2*pi*log2(BPM)) to equate
       half-time and double-time tempos, plus standardized log2(BPM) for absolute tempo.
    2. Feature standardization: StandardScaler across loudness, danceability,
       energy, and 7 mood probabilities.
    3. Neural embedding dimension reduction: PCA reduction down to configured components.
    4. Group weighting: Multiplies each block by configurable weights from Settings.
    5. Unit normalization: Projects each composite vector onto the unit hypersphere (L2=1).

    Args:
        tracks_data: List of database rows or dictionary records containing audio features.
        settings: Application settings containing weights. Defaults to get_settings().

    Returns:
        tuple containing:
            - track_ids (np.ndarray): 1D array of integer track IDs.
            - vectors (np.ndarray): 2D float32 array of shape (N, D) with unit L2 norm.
            - metadata_map (dict): Mapping from track_id to dictionary of track metadata.
    """
    cfg = settings or get_settings()

    if not tracks_data:
        logger.warning("No track feature records provided to build_vibe_vectors")
        return (
            np.empty(0, dtype=np.int64),
            np.empty((0, 0), dtype=np.float32),
            {},
        )

    n_samples = len(tracks_data)
    track_ids: list[int] = []
    bpms: list[float] = []
    loudness_vals: list[float] = []
    dance_vals: list[float] = []
    energy_vals: list[float] = []
    mood_rows: list[list[float]] = []
    raw_embeddings: list[np.ndarray] = []
    metadata_map: dict[int, dict[str, Any]] = {}

    for row in tracks_data:
        # Support sqlite3.Row, dict, or tuple/object
        if hasattr(row, "keys"):
            tid = int(row["track_id"])
            bpm = float(row["bpm"]) if row["bpm"] is not None and row["bpm"] > 0 else 120.0
            loud = float(row["loudness"]) if row["loudness"] is not None else -10.0
            dance = float(row["danceability"]) if row["danceability"] is not None else 0.5
            energy = float(row["energy"]) if row["energy"] is not None else 0.5

            mood_raw = row["mood_scores"]
            if isinstance(mood_raw, str):
                try:
                    mood_dict = json.loads(mood_raw)
                except Exception:
                    mood_dict = {}
            elif isinstance(mood_raw, dict):
                mood_dict = mood_raw
            else:
                mood_dict = {}

            emb_blob = row["embedding"]
            title = row["title"] if "title" in row.keys() else None
            artist = row["artist"] if "artist" in row.keys() else None
            album = row["album"] if "album" in row.keys() else None
            path = row["path"] if "path" in row.keys() else None
        else:
            # Fallback for dict-like
            tid = int(row.get("track_id", 0))
            bpm = float(row.get("bpm") or 120.0)
            loud = float(row.get("loudness") or -10.0)
            dance = float(row.get("danceability") or 0.5)
            energy = float(row.get("energy") or 0.5)
            mood_dict = row.get("mood_scores") or {}
            emb_blob = row.get("embedding")
            title = row.get("title")
            artist = row.get("artist")
            album = row.get("album")
            path = row.get("path")

        track_ids.append(tid)
        bpms.append(bpm)
        loudness_vals.append(loud)
        dance_vals.append(dance)
        energy_vals.append(energy)

        mood_row = [float(mood_dict.get(k, 0.0)) for k in MOOD_KEYS]
        mood_rows.append(mood_row)

        if emb_blob is not None and len(emb_blob) > 0:
            if isinstance(emb_blob, (bytes, bytearray, memoryview)):
                emb_arr = np.frombuffer(emb_blob, dtype=np.float32)
            elif isinstance(emb_blob, np.ndarray):
                emb_arr = emb_blob.astype(np.float32)
            else:
                emb_arr = np.array(emb_blob, dtype=np.float32)
        else:
            emb_arr = np.zeros(128, dtype=np.float32)

        raw_embeddings.append(emb_arr)

        metadata_map[tid] = {
            "track_id": tid,
            "title": title or "Unknown Title",
            "artist": artist or "Unknown Artist",
            "album": album or "Unknown Album",
            "bpm": bpm,
            "loudness": loud,
            "danceability": dance,
            "energy": energy,
            "mood_scores": {k: mood_row[i] for i, k in enumerate(MOOD_KEYS)},
            "path": path,
        }

    # 1. BPM representation: circular octave angle + absolute log2 tempo
    bpms_arr = np.array(bpms, dtype=np.float32)
    # Circular tempo: theta = 2 * pi * log2(BPM). Note that 2*BPM adds 2*pi, keeping harmonic point identical
    thetas = 2.0 * np.pi * np.log2(np.clip(bpms_arr, 1.0, 500.0))
    harmonic_bpm = np.column_stack([np.cos(thetas), np.sin(thetas)]).astype(np.float32)

    log_bpm = np.log2(np.clip(bpms_arr, 1.0, 500.0)).reshape(-1, 1).astype(np.float32)
    if n_samples > 1:
        abs_bpm = StandardScaler().fit_transform(log_bpm).astype(np.float32)
    else:
        abs_bpm = np.zeros_like(log_bpm, dtype=np.float32)

    # 2. Standardize scalar audio properties
    loudness_mat = np.array(loudness_vals, dtype=np.float32).reshape(-1, 1)
    dance_mat = np.array(dance_vals, dtype=np.float32).reshape(-1, 1)
    energy_mat = np.array(energy_vals, dtype=np.float32).reshape(-1, 1)
    moods_mat = np.array(mood_rows, dtype=np.float32)

    if n_samples > 1:
        std_loud = StandardScaler().fit_transform(loudness_mat).astype(np.float32)
        std_dance = StandardScaler().fit_transform(dance_mat).astype(np.float32)
        std_energy = StandardScaler().fit_transform(energy_mat).astype(np.float32)
        std_moods = StandardScaler().fit_transform(moods_mat).astype(np.float32)
    else:
        std_loud = np.zeros_like(loudness_mat, dtype=np.float32)
        std_dance = np.zeros_like(dance_mat, dtype=np.float32)
        std_energy = np.zeros_like(energy_mat, dtype=np.float32)
        std_moods = np.zeros_like(moods_mat, dtype=np.float32)

    # 3. PCA-reduced embeddings
    max_emb_len = max(len(e) for e in raw_embeddings)
    padded_embeddings = np.zeros((n_samples, max_emb_len), dtype=np.float32)
    for i, e in enumerate(raw_embeddings):
        padded_embeddings[i, : len(e)] = e

    target_pca_dims = max(1, cfg.pca_embedding_dimensions)
    n_pca_components = min(target_pca_dims, n_samples - 1, max_emb_len)

    if n_pca_components >= 1 and n_samples > 1:
        sample_var = float(np.var(padded_embeddings))
        if sample_var > 1e-6:
            scaled_emb = StandardScaler().fit_transform(padded_embeddings)
            total_var = float(np.var(scaled_emb, ddof=1, axis=0).sum())
            if total_var > 1e-6:
                pca = PCA(n_components=n_pca_components, random_state=42)
                emb_pca = pca.fit_transform(scaled_emb).astype(np.float32)
            else:
                emb_pca = np.zeros((n_samples, min(target_pca_dims, max_emb_len)), dtype=np.float32)
        else:
            emb_pca = np.zeros((n_samples, min(target_pca_dims, max_emb_len)), dtype=np.float32)
    else:
        # Fallback for single track, zero samples, or constant synthetic embeddings
        emb_pca = np.zeros((n_samples, min(target_pca_dims, max_emb_len)), dtype=np.float32)

    # 4. Weight application per feature block
    w_bpm = float(cfg.weight_bpm)
    w_loud = float(cfg.weight_loudness)
    w_dance = float(cfg.weight_danceability)
    w_energy = float(cfg.weight_energy)
    w_mood = float(cfg.weight_mood)
    w_emb = float(cfg.weight_embedding)
    h_ratio = float(np.clip(cfg.bpm_harmonic_weight, 0.0, 1.0))

    # BPM weighted components
    part_harmonic = harmonic_bpm * (w_bpm * np.sqrt(h_ratio / 2.0))
    part_abs = abs_bpm * (w_bpm * np.sqrt(1.0 - h_ratio))

    # Scalar weighted components
    part_loud = std_loud * w_loud
    part_dance = std_dance * w_dance
    part_energy = std_energy * w_energy
    part_mood = std_moods * (w_mood / np.sqrt(len(MOOD_KEYS)))

    # Embedding weighted component
    emb_dim = max(1, emb_pca.shape[1])
    part_emb = emb_pca * (w_emb / np.sqrt(emb_dim))

    # 5. Concatenation and L2 normalization
    composite = np.hstack(
        [
            part_harmonic,
            part_abs,
            part_loud,
            part_dance,
            part_energy,
            part_mood,
            part_emb,
        ]
    ).astype(np.float32)

    norms = np.linalg.norm(composite, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    vibe_vectors = (composite / norms).astype(np.float32)

    logger.debug(
        "Constructed %d vibe vectors (dimension=%d)",
        len(vibe_vectors),
        vibe_vectors.shape[1],
    )
    return np.array(track_ids, dtype=np.int64), vibe_vectors, metadata_map


def get_or_build_vibe_vectors(
    db_path: Path | None = None,
    rebuild_cache: bool = False,
    settings: Settings | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[int, dict[str, Any]]]:
    """Retrieve vibe vectors from disk cache or compute and cache them.

    The cache is invalidated when:
    - Features in the database change (detected via features table checksum).
    - Vibe vector configuration weights or PCA dimensions change.
    - rebuild_cache is explicitly set to True.

    Args:
        db_path: Optional path to the SQLite database.
        rebuild_cache: If True, forces recomputing vectors even if cache is valid.
        settings: Application settings.

    Returns:
        tuple containing (track_ids, vectors, metadata_map).
    """
    cfg = settings or get_settings()
    target_db = db_path or cfg.db_path
    cache_path = cfg.get_vector_cache_path(target_db)

    with get_connection(target_db) as conn:
        feature_checksum = get_features_checksum(conn)
        config_signature = _compute_config_signature(cfg)
        cache_key = f"{feature_checksum}:{config_signature}"

        # Try loading from cache
        if not rebuild_cache and cache_path.is_file():
            try:
                with np.load(cache_path, allow_pickle=False) as data:
                    stored_key = str(data["cache_key"])
                    if stored_key == cache_key:
                        track_ids = data["track_ids"]
                        vectors = data["vectors"]
                        logger.debug(
                            "Loaded %d vibe vectors from cache: %s",
                            len(track_ids),
                            cache_path,
                        )

                        # Fetch metadata map from database
                        tracks_rows = get_tracks_with_features(conn)
                        metadata_map = {}
                        for r in tracks_rows:
                            tid = int(r["track_id"])
                            try:
                                mood_dict = json.loads(r["mood_scores"]) if r["mood_scores"] else {}
                            except Exception:
                                mood_dict = {}
                            metadata_map[tid] = {
                                "track_id": tid,
                                "title": r["title"] or "Unknown Title",
                                "artist": r["artist"] or "Unknown Artist",
                                "album": r["album"] or "Unknown Album",
                                "bpm": float(r["bpm"]) if r["bpm"] is not None else 120.0,
                                "loudness": float(r["loudness"]) if r["loudness"] is not None else -10.0,
                                "danceability": float(r["danceability"]) if r["danceability"] is not None else 0.5,
                                "energy": float(r["energy"]) if r["energy"] is not None else 0.5,
                                "mood_scores": mood_dict,
                                "path": r["path"],
                            }
                        return track_ids, vectors, metadata_map
                    logger.info("Vector cache invalidated (checksum or settings changed). Recomputing...")
            except Exception as err:
                logger.warning(
                    "Failed to load vector cache from %s: %s. Recomputing...",
                    cache_path,
                    err,
                )

        # Recompute vectors
        tracks_rows = get_tracks_with_features(conn)
        track_ids, vectors, metadata_map = build_vibe_vectors(tracks_rows, settings=cfg)

        # Persist to disk cache
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                cache_path,
                track_ids=track_ids,
                vectors=vectors,
                cache_key=cache_key,
            )
            logger.debug("Saved %d vibe vectors to cache: %s", len(track_ids), cache_path)
        except Exception as err:
            logger.warning("Could not persist vector cache to %s: %s", cache_path, err)

        return track_ids, vectors, metadata_map


def similar_to(
    track_id: int,
    n: int = 10,
    db_path: Path | None = None,
    rebuild_cache: bool = False,
    settings: Settings | None = None,
) -> list[SimilarTrack]:
    """Find the top-N most similar tracks using cosine similarity over vibe vectors.

    Args:
        track_id: Database ID of the query track.
        n: Number of nearest neighbors to return.
        db_path: Optional path to SQLite database.
        rebuild_cache: If True, forces recomputing cached vectors.
        settings: Application settings.

    Returns:
        list[SimilarTrack]: Ranked list of similar tracks in descending similarity order.

    Raises:
        ValueError: If track_id is not found in the analyzed tracks dataset.
    """
    track_ids, vectors, metadata_map = get_or_build_vibe_vectors(
        db_path=db_path,
        rebuild_cache=rebuild_cache,
        settings=settings,
    )

    if len(track_ids) == 0:
        logger.warning("No analyzed tracks available for similarity query")
        return []

    # Locate query index
    indices = np.where(track_ids == track_id)[0]
    if len(indices) == 0:
        raise ValueError(f"Track ID {track_id} not found in analyzed audio library.")

    query_idx = int(indices[0])
    query_vector = vectors[query_idx]

    # Cosine similarity is dot product because vectors are unit L2 normalized
    similarities = np.dot(vectors, query_vector)

    # Sort descending by similarity
    ranked_indices = np.argsort(-similarities)

    results: list[SimilarTrack] = []
    for idx in ranked_indices:
        curr_id = int(track_ids[idx])
        if curr_id == track_id:
            # Skip self in nearest neighbors
            continue

        meta = metadata_map.get(curr_id, {})
        sim = float(similarities[idx])
        results.append(
            SimilarTrack(
                track_id=curr_id,
                similarity=sim,
                title=meta.get("title"),
                artist=meta.get("artist"),
                album=meta.get("album"),
                bpm=meta.get("bpm"),
                path=meta.get("path"),
            )
        )
        if len(results) >= n:
            break

    return results


def compute_clusters(
    db_path: Path | None = None,
    k: int = 5,
    algorithm: str = "kmeans",
    min_cluster_size: int = 3,
    rebuild_cache: bool = False,
    settings: Settings | None = None,
) -> ClusteringResult:
    """Cluster analyzed library tracks using KMeans or HDBSCAN.

    Args:
        db_path: Optional path to the SQLite database.
        k: Target number of clusters for KMeans.
        algorithm: Clustering algorithm ('kmeans' or 'hdbscan').
        min_cluster_size: Minimum cluster size for HDBSCAN.
        rebuild_cache: If True, force recomputing cached vibe vectors.
        settings: Application settings.

    Returns:
        ClusteringResult: Container holding cluster summaries, dominant moods,
        top artists, and representative tracks closest to each centroid.
    """
    cfg = settings or get_settings()
    track_ids, vectors, metadata_map = get_or_build_vibe_vectors(
        db_path=db_path,
        rebuild_cache=rebuild_cache,
        settings=cfg,
    )

    total_tracks = len(track_ids)
    if total_tracks == 0:
        logger.warning("No analyzed tracks found to cluster")
        return ClusteringResult(
            algorithm=algorithm,
            k=k,
            total_tracks=0,
            clusters=[],
        )

    algo = algorithm.lower().strip()
    if algo not in ("kmeans", "hdbscan"):
        raise ValueError(f"Unsupported clustering algorithm: '{algorithm}'. Must be 'kmeans' or 'hdbscan'.")

    # Perform clustering
    if algo == "kmeans":
        effective_k = min(k, total_tracks)
        kmeans = KMeans(n_clusters=effective_k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(vectors)
        unique_labels = sorted(set(labels))
        # Raw centroids
        centroids = kmeans.cluster_centers_
        # Normalize centroids
        centroid_norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        centroid_norms[centroid_norms == 0.0] = 1.0
        normalized_centroids = {label: (centroids[label] / centroid_norms[label]) for label in unique_labels}
    else:
        # HDBSCAN
        eff_min_size = max(2, min(min_cluster_size, total_tracks))
        hdb = HDBSCAN(min_cluster_size=eff_min_size, metric="euclidean", copy=True)
        labels = hdb.fit_predict(vectors)
        unique_labels = sorted(set(labels))
        normalized_centroids = {}
        for lbl in unique_labels:
            if lbl >= 0:
                cluster_members = vectors[labels == lbl]
                c_mean = np.mean(cluster_members, axis=0)
                norm = np.linalg.norm(c_mean)
                normalized_centroids[lbl] = c_mean / (norm if norm > 0 else 1.0)

    cluster_summaries: list[ClusterSummary] = []

    for cluster_label in unique_labels:
        mask = labels == cluster_label
        indices = np.where(mask)[0]
        member_track_ids = [int(track_ids[i]) for i in indices]
        member_size = len(member_track_ids)

        if cluster_label == -1:
            label_name = "Noise / Unclustered"
        else:
            label_name = f"Cluster {int(cluster_label) + 1}"

        # 1. Average BPM
        member_bpms = [float(metadata_map[tid]["bpm"]) for tid in member_track_ids if tid in metadata_map]
        avg_bpm = float(np.mean(member_bpms)) if member_bpms else 0.0

        # 2. Dominant Moods
        mood_sums: dict[str, float] = {mood_key: 0.0 for mood_key in MOOD_KEYS}
        for tid in member_track_ids:
            track_moods = metadata_map.get(tid, {}).get("mood_scores", {})
            for mood_key in MOOD_KEYS:
                mood_sums[mood_key] += float(track_moods.get(mood_key, 0.0))

        avg_moods = [(mood_key, mood_sums[mood_key] / member_size) for mood_key in MOOD_KEYS]
        avg_moods.sort(key=lambda x: x[1], reverse=True)
        dominant_moods = avg_moods[:3]

        # 3. Top 5 Artists
        artist_counts: dict[str, int] = {}
        for tid in member_track_ids:
            art = metadata_map.get(tid, {}).get("artist") or "Unknown"
            artist_counts[art] = artist_counts.get(art, 0) + 1

        top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # 4. Top 5 Representative Tracks (closest to centroid)
        representative_tracks: list[dict[str, Any]] = []
        if cluster_label in normalized_centroids:
            centroid_vec = normalized_centroids[cluster_label]
            member_vectors = vectors[indices]
            sims_to_centroid = np.dot(member_vectors, centroid_vec)
            sorted_member_order = np.argsort(-sims_to_centroid)

            for order_idx in sorted_member_order[:5]:
                global_idx = indices[order_idx]
                tid = int(track_ids[global_idx])
                meta = metadata_map.get(tid, {})
                representative_tracks.append(
                    {
                        "track_id": tid,
                        "title": meta.get("title"),
                        "artist": meta.get("artist"),
                        "album": meta.get("album"),
                        "bpm": meta.get("bpm"),
                        "similarity_to_centroid": float(sims_to_centroid[order_idx]),
                    }
                )
        else:
            # For noise without a centroid, take first 5
            for tid in member_track_ids[:5]:
                meta = metadata_map.get(tid, {})
                representative_tracks.append(
                    {
                        "track_id": tid,
                        "title": meta.get("title"),
                        "artist": meta.get("artist"),
                        "album": meta.get("album"),
                        "bpm": meta.get("bpm"),
                        "similarity_to_centroid": 0.0,
                    }
                )

        cluster_summaries.append(
            ClusterSummary(
                cluster_id=int(cluster_label),
                label=label_name,
                size=member_size,
                avg_bpm=round(avg_bpm, 1),
                dominant_moods=[(m, round(s, 3)) for m, s in dominant_moods],
                top_artists=top_artists,
                representative_tracks=representative_tracks,
                track_ids=member_track_ids,
            )
        )

    # Sort clusters: normal clusters first by size descending, then noise at the end
    cluster_summaries.sort(key=lambda c: (1 if c.cluster_id == -1 else 0, -c.size))

    return ClusteringResult(
        algorithm=algo,
        k=len(cluster_summaries),
        total_tracks=total_tracks,
        clusters=cluster_summaries,
    )
