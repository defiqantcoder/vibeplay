"""Abstract audio analyzer base class and audio stream utilities."""

import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioFeatures:
    """Normalized audio features extracted from an audio track."""

    track_id: int
    analyzer_version: str
    bpm: float | None
    key: str | None
    scale: str | None
    loudness: float | None
    danceability: float | None
    energy: float | None
    mood_scores: dict[str, float]
    embedding: np.ndarray

    def embedding_bytes(self) -> bytes:
        """Return raw float32 byte array of the embedding vector.

        Returns:
            bytes: Binary representation suitable for SQLite BLOB storage.
        """
        return self.embedding.astype(np.float32).tobytes()


class BaseAnalyzer(ABC):
    """Abstract interface for audio feature extractors."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Version string identifying the analyzer implementation.

        Returns:
            str: Analyzer version (e.g. 'essentia-1.0.0' or 'librosa-1.0.0').
        """
        ...

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Audio sample rate in Hz expected by this analyzer."""
        ...

    @abstractmethod
    def extract_features(
        self,
        audio: np.ndarray,
        track_id: int,
    ) -> AudioFeatures:
        """Extract acoustic features and embedding from pre-decoded audio samples.

        Args:
            audio: 2D float32 audio samples of shape (samples, channels).
            track_id: Database track ID.

        Returns:
            AudioFeatures: Extracted feature dataclass.
        """
        ...

    def analyze_track(
        self,
        path: Path,
        track_id: int,
        duration: float | None = None,
        window_seconds: float = 60.0,
    ) -> AudioFeatures:
        """Decode a 60-second middle window via ffmpeg and extract features.

        Guarantees strictly read-only access to audio files.

        Args:
            path: Path to the audio file.
            track_id: Database track ID.
            duration: Total duration of the track in seconds (if known).
            window_seconds: Length of analysis window in seconds.

        Returns:
            AudioFeatures: Extracted features.
        """
        offset = get_middle_window_offset(duration or 0.0, window_seconds=window_seconds)
        audio = decode_audio_slice(
            path=path,
            offset_seconds=offset,
            duration_seconds=window_seconds,
            sample_rate=self.sample_rate,
        )
        return self.extract_features(audio=audio, track_id=track_id)


def get_middle_window_offset(duration: float, window_seconds: float = 60.0) -> float:
    """Calculate the starting offset for a window centered in the track.

    Args:
        duration: Total duration of the track in seconds.
        window_seconds: Desired window length.

    Returns:
        float: Start offset in seconds (always >= 0.0).
    """
    if duration <= window_seconds or duration <= 0:
        return 0.0
    return (duration - window_seconds) / 2.0


def downmix_to_mono(audio: np.ndarray) -> np.ndarray:
    """Downmix a multichannel audio array to mono by averaging channels.

    Args:
        audio: 2D array of shape (samples, channels) or 1D array of shape (samples,).

    Returns:
        np.ndarray: 1D array of shape (samples,).
    """
    if audio.ndim == 1:
        return audio
    return np.mean(audio, axis=1)


def decode_audio_slice(
    path: Path,
    offset_seconds: float,
    duration_seconds: float = 60.0,
    sample_rate: int = 44100,
) -> np.ndarray:
    """Decode a slice of audio from disk into mono float32 samples using ffmpeg.

    Guarantees strict read-only access to the source audio file.
    Gracefully falls back to offset 0.0 if offset sought past the actual file duration.

    Args:
        path: Path to the audio file.
        offset_seconds: Start timestamp in seconds.
        duration_seconds: Duration to decode in seconds.
        sample_rate: Output sample rate in Hz.

    Returns:
        np.ndarray: 2D float32 numpy array of shape (samples, 2).

    Raises:
        RuntimeError: If ffmpeg decoding fails or returns empty output.
    """
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{max(0.0, offset_seconds):.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        "2",
        "pipe:1",
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as err:
        err_msg = err.stderr.decode("utf-8", errors="replace").strip()
        logger.error("ffmpeg decoding failed for %s: %s", path, err_msg)
        raise RuntimeError(f"ffmpeg failed to decode {path}: {err_msg}") from err

    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    # reshape interleaved stereo to (samples, 2)
    samples = samples.reshape(-1, 2)

    # If seeking past EOF yielded 0 samples, retry from offset 0.0
    if len(samples) == 0 and offset_seconds > 0.0:
        logger.debug(
            "Seeking to %.2fs on %s yielded 0 samples; falling back to offset 0.0s",
            offset_seconds,
            path,
        )
        return decode_audio_slice(
            path=path,
            offset_seconds=0.0,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
        )

    if len(samples) == 0:
        raise RuntimeError(f"ffmpeg decoded 0 samples from {path}")

    return samples
