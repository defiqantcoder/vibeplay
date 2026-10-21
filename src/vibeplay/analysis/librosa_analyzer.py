"""Librosa-based fallback audio analyzer extracting BPM, key, loudness, danceability, moods, and embeddings."""

import logging
from typing import Any

import librosa
import numpy as np

from vibeplay.analysis.base import AudioFeatures, BaseAnalyzer

logger = logging.getLogger(__name__)

# Krumhansl-Schmuckler musical key profiles
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class LibrosaAnalyzer(BaseAnalyzer):
    """Audio feature extractor powered by librosa as a reliable fallback."""

    def __init__(self) -> None:
        self._version = "librosa-1.0.0"
        self._sample_rate = 22050

    @property
    def version(self) -> str:
        return self._version

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def _estimate_key(self, chroma_mean: np.ndarray) -> tuple[str, str]:
        """Estimate key and scale from chroma profile correlation.

        Args:
            chroma_mean: 12-element mean chroma vector.

        Returns:
            tuple[str, str]: (key, scale) e.g. ('A', 'minor').
        """
        scores: dict[tuple[str, str], float] = {}
        for idx, pitch in enumerate(PITCH_CLASSES):
            maj_corr = float(np.corrcoef(chroma_mean, np.roll(MAJOR_PROFILE, idx))[0, 1])
            min_corr = float(np.corrcoef(chroma_mean, np.roll(MINOR_PROFILE, idx))[0, 1])
            scores[(pitch, "major")] = maj_corr
            scores[(pitch, "minor")] = min_corr

        best_key, best_scale = max(scores, key=scores.get)
        return best_key, best_scale

    def extract_features(
        self,
        audio: np.ndarray,
        track_id: int,
    ) -> AudioFeatures:
        """Extract acoustic features and 128-dim embedding using librosa.

        Args:
            audio: 1D float32 audio waveform samples.
            track_id: Database track ID.

        Returns:
            AudioFeatures: Extracted features.
        """
        # Rhythm / BPM
        try:
            tempo, _ = librosa.beat.beat_track(y=audio, sr=self._sample_rate)
            bpm_val = float(tempo[0] if isinstance(tempo, (list, np.ndarray)) else tempo)
            bpm = round(bpm_val, 2)
        except Exception as err:
            logger.debug("Librosa beat_track failed on track %d: %s", track_id, err)
            bpm = None

        # Chroma and Key/Scale
        try:
            chroma = librosa.feature.chroma_stft(y=audio, sr=self._sample_rate)
            chroma_mean = np.mean(chroma, axis=1)
            key, scale = self._estimate_key(chroma_mean)
        except Exception as err:
            logger.debug("Librosa key estimation failed on track %d: %s", track_id, err)
            key, scale = None, None
            chroma_mean = np.zeros(12, dtype=np.float32)

        # RMS Energy and Loudness
        try:
            rms_frames = librosa.feature.rms(y=audio)[0]
            rms_val = float(np.mean(rms_frames))
            energy = float(round(np.clip(rms_val * 4.0, 0.0, 1.0), 4))
            # Approximate LUFS / dB from RMS
            loudness = float(round(20.0 * np.log10(max(rms_val, 1e-5)), 2))
        except Exception:
            energy, loudness = 0.5, -14.0

        # Danceability (regularity of onset strength peaks)
        try:
            onset_env = librosa.onset.onset_strength(y=audio, sr=self._sample_rate)
            autocorr = librosa.autocorrelate(onset_env, max_size=int(self._sample_rate / 64))
            if len(autocorr) > 1 and autocorr[0] > 0:
                dance_score = float(np.max(autocorr[1:]) / autocorr[0])
                danceability = float(round(np.clip(dance_score * 1.5, 0.0, 1.0), 4))
            else:
                danceability = 0.5
        except Exception as err:
            logger.debug("Librosa danceability estimation failed: %s", err)
            danceability = 0.5

        # MFCC and Spectral features for Embedding
        try:
            mfcc = librosa.feature.mfcc(y=audio, sr=self._sample_rate, n_mfcc=20)
            mfcc_mean = np.mean(mfcc, axis=1)
            mfcc_std = np.std(mfcc, axis=1)

            spectral_centroid = librosa.feature.spectral_centroid(y=audio, sr=self._sample_rate)[0]
            sc_norm = float(np.mean(spectral_centroid) / (self._sample_rate / 2.0))

            spectral_contrast = librosa.feature.spectral_contrast(y=audio, sr=self._sample_rate)
            sc_mean = np.mean(spectral_contrast, axis=1)
        except Exception:
            mfcc_mean = np.zeros(20, dtype=np.float32)
            mfcc_std = np.zeros(20, dtype=np.float32)
            sc_norm = 0.5
            sc_mean = np.zeros(7, dtype=np.float32)

        # Assemble 128-dimensional embedding
        feature_concat = np.concatenate([
            mfcc_mean,
            mfcc_std,
            chroma_mean,
            sc_mean,
            np.array([
                bpm / 200.0 if bpm else 0.5,
                energy,
                danceability,
                (loudness + 70.0) / 70.0,
                sc_norm,
            ], dtype=np.float32),
        ])
        embedding = np.pad(feature_concat, (0, max(0, 128 - len(feature_concat))), mode="constant")[:128].astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        # Mood scores
        is_major = 1.0 if scale == "major" else 0.0
        norm_bpm = np.clip(((bpm or 120.0) - 60.0) / 100.0, 0.0, 1.0)
        norm_loud = np.clip((loudness + 30.0) / 30.0, 0.0, 1.0)

        happy = float(np.clip(0.4 * is_major + 0.3 * danceability + 0.3 * norm_bpm, 0.0, 1.0))
        sad = float(np.clip(0.5 * (1.0 - is_major) + 0.3 * (1.0 - norm_bpm) + 0.2 * (1.0 - energy), 0.0, 1.0))
        relaxed = float(np.clip(0.5 * (1.0 - energy) + 0.3 * (1.0 - norm_loud) + 0.2 * (1.0 - danceability), 0.0, 1.0))
        aggressive = float(np.clip(0.5 * energy + 0.3 * norm_loud + 0.2 * norm_bpm, 0.0, 1.0))
        party = float(np.clip(0.4 * danceability + 0.3 * energy + 0.3 * (1.0 - abs(norm_bpm - 0.65)), 0.0, 1.0))
        acoustic = float(np.clip(0.5 * (1.0 - norm_loud) + 0.3 * (1.0 - energy) + 0.2 * (1.0 - danceability), 0.0, 1.0))
        electronic = float(np.clip(0.4 * danceability + 0.3 * energy + 0.3 * norm_loud, 0.0, 1.0))

        mood_scores = {
            "happy": round(happy, 4),
            "sad": round(sad, 4),
            "relaxed": round(relaxed, 4),
            "aggressive": round(aggressive, 4),
            "party": round(party, 4),
            "acoustic": round(acoustic, 4),
            "electronic": round(electronic, 4),
        }

        return AudioFeatures(
            track_id=track_id,
            analyzer_version=self.version,
            bpm=bpm,
            key=key,
            scale=scale,
            loudness=loudness,
            danceability=danceability,
            energy=energy,
            mood_scores=mood_scores,
            embedding=embedding,
        )
