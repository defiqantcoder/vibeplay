"""Essentia-based audio analyzer extracting BPM, key, loudness, danceability, moods, and embeddings."""

import logging
from pathlib import Path

import numpy as np

from vibeplay.analysis.base import AudioFeatures, BaseAnalyzer

logger = logging.getLogger(__name__)

ESSENTIA_MODELS = {
    "effnet": "discogs-effnet-bs64-1.pb",
    "happy": "mood_happy-discogs-effnet-1.pb",
    "sad": "mood_sad-discogs-effnet-1.pb",
    "relaxed": "mood_relaxed-discogs-effnet-1.pb",
    "aggressive": "mood_aggressive-discogs-effnet-1.pb",
    "party": "mood_party-discogs-effnet-1.pb",
    "acoustic": "mood_acoustic-discogs-effnet-1.pb",
    "electronic": "mood_electronic-discogs-effnet-1.pb",
}


class EssentiaAnalyzer(BaseAnalyzer):
    """Audio feature extractor powered by Essentia and pretrained TensorFlow models."""

    def __init__(self, models_dir: Path | None = None) -> None:
        self._version = "essentia-1.0.0"
        self._sample_rate = 44100
        self.models_dir = (models_dir or Path("models")).resolve()

    @property
    def version(self) -> str:
        return self._version

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def _extract_tf_models(
        self,
        audio_16k: np.ndarray,
    ) -> tuple[np.ndarray | None, dict[str, float] | None]:
        """Run Discogs-EffNet and mood classification models if weights are present.

        Args:
            audio_16k: Audio waveform resampled to 16,000 Hz.

        Returns:
            tuple[np.ndarray | None, dict[str, float] | None]: (embedding, mood_scores)
        """
        import essentia.standard as es

        effnet_file = self.models_dir / ESSENTIA_MODELS["effnet"]
        if not effnet_file.exists():
            return None, None

        try:
            effnet_model = es.TensorflowPredictEffnetDiscogs(
                graphFilename=str(effnet_file),
                output="PartitionedCall:1",
            )
            raw_embeddings = effnet_model(audio_16k)
            # Frame-level embeddings: shape (frames, 1280) -> mean pool to (1280,)
            embedding = np.mean(raw_embeddings, axis=0).astype(np.float32)
        except Exception as err:
            logger.warning("Failed running Discogs-EffNet model: %s", err)
            return None, None

        moods: dict[str, float] = {}
        for mood_key in (
            "happy",
            "sad",
            "relaxed",
            "aggressive",
            "party",
            "acoustic",
            "electronic",
        ):
            mood_file = self.models_dir / ESSENTIA_MODELS[mood_key]
            if mood_file.exists():
                try:
                    classifier = es.TensorflowPredict2D(graphFilename=str(mood_file))
                    preds = classifier(raw_embeddings)
                    # Binary classification: positive class probability is at index 0 or 1
                    prob = float(np.mean(preds[:, 0])) if preds.ndim > 1 else float(np.mean(preds))
                    moods[mood_key] = float(np.clip(prob, 0.0, 1.0))
                except Exception as err:
                    logger.debug("Could not infer mood '%s': %s", mood_key, err)

        return embedding, moods if len(moods) == 7 else None

    def _extract_fallback_embeddings_and_moods(
        self,
        audio: np.ndarray,
        bpm: float,
        key: str,
        scale: str,
        loudness: float,
        danceability: float,
        energy: float,
    ) -> tuple[np.ndarray, dict[str, float]]:
        """Compute heuristic mood scores and spectral embedding when ML models are absent."""
        import essentia.standard as es

        # Compute 128-dimensional spectral embedding vector
        w = es.Windowing(type="hann")
        spectrum = es.Spectrum()
        mfcc = es.MFCC(numberCoefficients=40)

        mfcc_frames = []
        for frame in es.FrameGenerator(audio, frameSize=2048, hopSize=1024, startFromZero=True):
            _, mfcc_coeffs = mfcc(spectrum(w(frame)))
            mfcc_frames.append(mfcc_coeffs)

        if mfcc_frames:
            mfcc_mat = np.array(mfcc_frames)
            mfcc_mean = np.mean(mfcc_mat, axis=0)
            mfcc_std = np.std(mfcc_mat, axis=0)
        else:
            mfcc_mean = np.zeros(40, dtype=np.float32)
            mfcc_std = np.zeros(40, dtype=np.float32)

        # Spectral summary features
        flux = es.Flux()(audio)
        roll_off = es.RollOff()(audio)

        # Assemble fixed-length 128 float32 vector
        summary = np.concatenate(
            [
                mfcc_mean[:40],
                mfcc_std[:40],
                np.array(
                    [
                        bpm / 200.0,
                        energy,
                        danceability,
                        (loudness + 70.0) / 70.0,
                        flux,
                        roll_off / 22050.0,
                    ],
                    dtype=np.float32,
                ),
            ]
        )
        embedding = np.pad(summary, (0, max(0, 128 - len(summary))), mode="constant")[:128].astype(np.float32)
        # Normalize embedding vector
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        # Heuristic mood calculations based on musical acoustics
        is_major = 1.0 if scale.lower() == "major" else 0.0
        norm_bpm = np.clip((bpm - 60.0) / 100.0, 0.0, 1.0)
        norm_loud = np.clip((loudness + 30.0) / 30.0, 0.0, 1.0)

        happy = float(np.clip(0.4 * is_major + 0.3 * danceability + 0.3 * norm_bpm, 0.0, 1.0))
        sad = float(
            np.clip(
                0.5 * (1.0 - is_major) + 0.3 * (1.0 - norm_bpm) + 0.2 * (1.0 - energy),
                0.0,
                1.0,
            )
        )
        relaxed = float(
            np.clip(
                0.5 * (1.0 - energy) + 0.3 * (1.0 - norm_loud) + 0.2 * (1.0 - danceability),
                0.0,
                1.0,
            )
        )
        aggressive = float(np.clip(0.5 * energy + 0.3 * norm_loud + 0.2 * norm_bpm, 0.0, 1.0))
        party = float(
            np.clip(
                0.4 * danceability + 0.3 * energy + 0.3 * (1.0 - abs(norm_bpm - 0.65)),
                0.0,
                1.0,
            )
        )
        acoustic = float(
            np.clip(
                0.5 * (1.0 - norm_loud) + 0.3 * (1.0 - energy) + 0.2 * (1.0 - danceability),
                0.0,
                1.0,
            )
        )
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

        return embedding, mood_scores

    def extract_features(
        self,
        audio: np.ndarray,
        track_id: int,
    ) -> AudioFeatures:
        """Extract acoustic features from audio samples using Essentia algorithms.

        Args:
            audio: 1D float32 audio samples at 44,100 Hz.
            track_id: Database track ID.

        Returns:
            AudioFeatures: Extracted feature metrics and embedding vector.
        """
        import essentia.standard as es

        # Rhythm / BPM
        try:
            rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
            bpm_val, _, _, _, _ = rhythm_extractor(audio)
            bpm = float(round(bpm_val, 2))
        except Exception as err:
            logger.debug("RhythmExtractor failed on track %d: %s", track_id, err)
            bpm = None

        # Key and Scale
        try:
            key_extractor = es.KeyExtractor()
            key_val, scale_val, _ = key_extractor(audio)
            key = str(key_val)
            scale = str(scale_val)
        except Exception as err:
            logger.debug("KeyExtractor failed on track %d: %s", track_id, err)
            key, scale = None, None

        # Integrated Loudness (LUFS) - requires stereo sample input
        try:
            ebur128 = es.LoudnessEBUR128(sampleRate=self._sample_rate)
            stereo_samples = np.vstack([audio, audio]).T
            _, _, integrated_loudness, _ = ebur128(stereo_samples)
            loudness = float(round(integrated_loudness, 2))
        except Exception as err:
            logger.debug("LoudnessEBUR128 failed on track %d: %s", track_id, err)
            loudness = None

        # Danceability (DFA exponent normalized to ~0.0 - 1.0)
        try:
            dance_extractor = es.Danceability()
            dance_val, _ = dance_extractor(audio)
            danceability = float(round(np.clip(dance_val / 3.0, 0.0, 1.0), 4))
        except Exception as err:
            logger.debug("Danceability failed on track %d: %s", track_id, err)
            danceability = None

        # Energy (Normalized RMS)
        try:
            rms = np.sqrt(np.mean(audio**2))
            energy = float(round(np.clip(rms * 4.0, 0.0, 1.0), 4))
        except Exception:
            energy = None

        # Resample to 16 kHz for Discogs-EffNet models
        try:
            resampler = es.Resample(inputSampleRate=self._sample_rate, outputSampleRate=16000)
            audio_16k = resampler(audio)
            tf_embedding, tf_moods = self._extract_tf_models(audio_16k)
        except Exception as err:
            logger.debug("Resampling/TF inference error on track %d: %s", track_id, err)
            tf_embedding, tf_moods = None, None

        if tf_embedding is not None and tf_moods is not None:
            embedding = tf_embedding
            mood_scores = tf_moods
        else:
            embedding, mood_scores = self._extract_fallback_embeddings_and_moods(
                audio=audio,
                bpm=bpm or 120.0,
                key=key or "C",
                scale=scale or "major",
                loudness=loudness or -14.0,
                danceability=danceability or 0.5,
                energy=energy or 0.5,
            )

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
