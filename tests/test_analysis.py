"""Unit tests for audio analysis and feature extraction."""

import shutil
import wave
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from vibeplay.analysis import (
    EssentiaAnalyzer,
    LibrosaAnalyzer,
    analyze_tracks,
    decode_audio_slice,
    downmix_to_mono,
    get_middle_window_offset,
)
from vibeplay.cli import app
from vibeplay.db import get_connection, init_db, insert_track

runner = CliRunner()


@pytest.fixture
def synthetic_wav_file(tmp_path: Path) -> Path:
    """Generate a 2-second 440 Hz synthetic PCM WAV file."""
    wav_path = tmp_path / "test_tone.wav"
    sample_rate = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # 440 Hz sine wave
    samples = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())

    return wav_path


@pytest.fixture
def db_with_two_tracks(tmp_path: Path, synthetic_wav_file: Path) -> Path:
    """Initialize a test database containing two active tracks."""
    db_path = tmp_path / "analysis_test.db"
    init_db(db_path)

    wav2 = tmp_path / "test_tone_2.wav"
    shutil.copyfile(synthetic_wav_file, wav2)

    with get_connection(db_path) as conn:
        for idx, file_path in ((1, synthetic_wav_file), (2, wav2)):
            insert_track(
                conn=conn,
                path=str(file_path),
                mtime=1700000000.0,
                size=file_path.stat().st_size,
                file_hash=f"hash_{idx}",
                duration=120.0,
                bitrate=1411200,
                title=f"Synthetic Track {idx}",
                artist="Test Artist",
                album_artist="Test Artist",
                album="Test Album",
                track_no=idx,
                track_total=2,
                disc_no=1,
                disc_total=1,
                year=2024,
                genre="Electronic",
                has_cover=False,
                tags_json="{}",
            )
    return db_path


def test_middle_window_offset() -> None:
    """Verify offset calculation for middle analysis window."""
    assert get_middle_window_offset(duration=180.0, window_seconds=60.0) == 60.0
    assert get_middle_window_offset(duration=60.0, window_seconds=60.0) == 0.0
    assert get_middle_window_offset(duration=45.0, window_seconds=60.0) == 0.0
    assert get_middle_window_offset(duration=0.0, window_seconds=60.0) == 0.0


def test_downmix_to_mono() -> None:
    """Verify multichannel array is correctly downmixed to mono."""
    stereo = np.array([[1.0, -1.0], [0.5, 0.5], [0.0, 0.0]], dtype=np.float32)
    mono = downmix_to_mono(stereo)
    assert mono.shape == (3,)
    np.testing.assert_array_almost_equal(mono, [0.0, 0.5, 0.0])

    mono_input = np.array([1.0, 0.5, 0.0], dtype=np.float32)
    mono_output = downmix_to_mono(mono_input)
    assert mono_output.shape == (3,)
    np.testing.assert_array_almost_equal(mono_output, [1.0, 0.5, 0.0])


def test_decode_audio_slice(synthetic_wav_file: Path) -> None:
    """Verify ffmpeg audio decoding produces expected float32 samples."""
    samples = decode_audio_slice(
        path=synthetic_wav_file,
        offset_seconds=0.0,
        duration_seconds=1.0,
        sample_rate=44100,
    )
    assert isinstance(samples, np.ndarray)
    assert samples.dtype == np.float32
    assert samples.shape == (44100, 2)
    assert -1.0 <= samples.min() <= samples.max() <= 1.0


def test_librosa_analyzer(synthetic_wav_file: Path) -> None:
    """Verify that LibrosaAnalyzer extracts expected acoustic features."""
    analyzer = LibrosaAnalyzer()
    assert analyzer.version == "librosa-1.0.0"
    assert analyzer.sample_rate == 22050

    features = analyzer.analyze_track(
        path=synthetic_wav_file,
        track_id=1,
        duration=2.0,
        window_seconds=1.0,
    )
    assert features.track_id == 1
    assert features.analyzer_version == "librosa-1.0.0"
    assert features.bpm is not None
    assert features.key == "A"
    assert features.scale in ("major", "minor")
    assert features.loudness is not None
    assert features.danceability is not None
    assert features.energy is not None
    assert "happy" in features.mood_scores
    assert "electronic" in features.mood_scores
    assert len(features.embedding) == 128
    assert len(features.embedding_bytes()) == 128 * 4


def test_essentia_analyzer(synthetic_wav_file: Path) -> None:
    """Verify that EssentiaAnalyzer extracts features using Essentia algorithms."""
    analyzer = EssentiaAnalyzer()
    assert analyzer.version == "essentia-1.0.0"
    assert analyzer.sample_rate == 44100

    features = analyzer.analyze_track(
        path=synthetic_wav_file,
        track_id=1,
        duration=2.0,
        window_seconds=1.0,
    )
    assert features.track_id == 1
    assert features.analyzer_version == "essentia-1.0.0"
    assert features.bpm is not None
    assert features.key is not None
    assert features.scale is not None
    assert features.loudness is not None
    assert features.danceability is not None
    assert features.energy is not None
    assert "happy" in features.mood_scores
    assert len(features.embedding) >= 128
    assert isinstance(features.embedding_bytes(), bytes)


def test_analyze_tracks_batch_and_resumable(db_with_two_tracks: Path) -> None:
    """Verify analyze_tracks inserts rows, computes averages, and skips already analyzed tracks."""
    # First pass: analyze both tracks using Librosa (sequential for testing)
    summary1 = analyze_tracks(
        db_path=db_with_two_tracks,
        backend="librosa",
        workers=1,
    )
    assert summary1.total_considered == 2
    assert summary1.analyzed == 2
    assert summary1.failed == 0
    assert summary1.avg_seconds_per_track > 0

    with get_connection(db_with_two_tracks) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT track_id, bpm, key, scale, embedding FROM features")
        rows = cursor.fetchall()
        assert len(rows) == 2
        for r in rows:
            assert r["bpm"] is not None
            assert len(r["embedding"]) > 0

    # Second pass: should skip both tracks because they are already analyzed with librosa-1.0.0
    summary2 = analyze_tracks(
        db_path=db_with_two_tracks,
        backend="librosa",
        workers=1,
    )
    assert summary2.total_considered == 0
    assert summary2.analyzed == 0


def test_cli_analyze_command(db_with_two_tracks: Path) -> None:
    """Verify vibeplay analyze CLI command runs successfully and prints timing."""
    result = runner.invoke(
        app,
        [
            "analyze",
            "--fallback-librosa",
            "--limit",
            "1",
            "--workers",
            "1",
            "--db",
            str(db_with_two_tracks),
        ],
    )
    assert result.exit_code == 0
    assert "Audio Analysis Summary" in result.stdout
    assert "Average Speed" in result.stdout
    assert "Full Library Estimate" in result.stdout
