"""Tests for scanner and database synchronization."""

import struct
import wave
from pathlib import Path

import pytest
from mutagen.id3 import APIC, TALB, TCON, TDRC, TIT2, TPE1, TRCK
from mutagen.wave import WAVE
from typer.testing import CliRunner

from vibeplay.cli import app
from vibeplay.db import get_connection
from vibeplay.scanner import scan_directory

runner = CliRunner()


def create_synthetic_wav(
    target_path: Path,
    title: str = "Test Title",
    artist: str = "Test Artist",
    album: str = "Test Album",
    track_no: str = "1/10",
    year: str = "2024",
    genre: str = "Electronic",
    with_cover: bool = False,
) -> Path:
    """Create a minimal valid PCM WAV file with ID3 tags using pure Python."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        # 0.05 seconds of audio samples
        wf.writeframes(struct.pack("<h", 0) * 2205)

    audio = WAVE(target_path)
    audio.add_tags()
    audio.tags.add(TIT2(encoding=3, text=[title]))
    audio.tags.add(TPE1(encoding=3, text=[artist]))
    audio.tags.add(TALB(encoding=3, text=[album]))
    audio.tags.add(TRCK(encoding=3, text=[track_no]))
    audio.tags.add(TDRC(encoding=3, text=[year]))
    audio.tags.add(TCON(encoding=3, text=[genre]))
    if with_cover:
        audio.tags.add(
            APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Front Cover",
                data=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9",
            )
        )
    audio.save()
    return target_path


@pytest.fixture
def synthetic_music_library(tmp_path: Path) -> Path:
    """Fixture providing a temporary music directory with two synthetic audio files."""
    music_dir = tmp_path / "music"
    music_dir.mkdir()

    create_synthetic_wav(
        music_dir / "Artist1" / "Album1" / "song1.wav",
        title="First Track",
        artist="Artist One",
        album="Album One",
        track_no="1/10",
        year="2023",
        genre="Ambient",
        with_cover=True,
    )

    create_synthetic_wav(
        music_dir / "Artist2" / "Album2" / "song2.wav",
        title="Second Track",
        artist="Artist Two",
        album="Album Two",
        track_no="2/10",
        year="2024",
        genre="Downtempo",
        with_cover=False,
    )

    return music_dir


def test_scan_new_files(synthetic_music_library: Path, tmp_path: Path) -> None:
    """Verify that a fresh scan indexes all audio files into SQLite."""
    db_path = tmp_path / "vibeplay.db"
    summary = scan_directory(synthetic_music_library, db_path)

    assert summary.new == 2
    assert summary.updated == 0
    assert summary.unchanged == 0
    assert summary.missing == 0
    assert summary.errors == 0

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, artist, album, track_no, year, genre, has_cover, status FROM tracks ORDER BY track_no"
        )
        rows = cursor.fetchall()

        assert len(rows) == 2
        assert rows[0]["title"] == "First Track"
        assert rows[0]["artist"] == "Artist One"
        assert rows[0]["album"] == "Album One"
        assert rows[0]["track_no"] == 1
        assert rows[0]["year"] == 2023
        assert rows[0]["genre"] == "Ambient"
        assert rows[0]["has_cover"] == 1
        assert rows[0]["status"] == "active"

        assert rows[1]["title"] == "Second Track"
        assert rows[1]["artist"] == "Artist Two"
        assert rows[1]["has_cover"] == 0
        assert rows[1]["status"] == "active"


def test_scan_incremental_unchanged(
    synthetic_music_library: Path, tmp_path: Path
) -> None:
    """Verify that rescanning an unchanged folder reports all tracks as unchanged."""
    db_path = tmp_path / "vibeplay.db"
    first_summary = scan_directory(synthetic_music_library, db_path)
    assert first_summary.new == 2

    second_summary = scan_directory(synthetic_music_library, db_path)
    assert second_summary.new == 0
    assert second_summary.updated == 0
    assert second_summary.unchanged == 2
    assert second_summary.missing == 0
    assert second_summary.errors == 0


def test_scan_updated_files(synthetic_music_library: Path, tmp_path: Path) -> None:
    """Verify that modifying a file's tags/size triggers an update."""
    db_path = tmp_path / "vibeplay.db"
    scan_directory(synthetic_music_library, db_path)

    # Modify song1.wav
    song1_path = synthetic_music_library / "Artist1" / "Album1" / "song1.wav"
    create_synthetic_wav(
        song1_path,
        title="Updated First Track",
        artist="Artist One",
        album="Album One",
        track_no="1/10",
        year="2025",
        genre="Modern Ambient",
        with_cover=False,
    )

    summary = scan_directory(synthetic_music_library, db_path)
    assert summary.new == 0
    assert summary.updated == 1
    assert summary.unchanged == 1
    assert summary.missing == 0
    assert summary.errors == 0

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, year, genre FROM tracks WHERE path = ?",
            (str(song1_path.resolve()),),
        )
        row = cursor.fetchone()
        assert row["title"] == "Updated First Track"
        assert row["year"] == 2025
        assert row["genre"] == "Modern Ambient"


def test_scan_removed_files_marked_missing(
    synthetic_music_library: Path, tmp_path: Path
) -> None:
    """Verify that deleted files are marked as missing rather than deleted from the database."""
    db_path = tmp_path / "vibeplay.db"
    scan_directory(synthetic_music_library, db_path)

    # Delete song2.wav from disk
    song2_path = synthetic_music_library / "Artist2" / "Album2" / "song2.wav"
    song2_path.unlink()

    summary = scan_directory(synthetic_music_library, db_path)
    assert summary.new == 0
    assert summary.updated == 0
    assert summary.unchanged == 1
    assert summary.missing == 1
    assert summary.errors == 0

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT path, status FROM tracks ORDER BY id")
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert rows[0]["status"] == "active"
        assert rows[1]["status"] == "missing"
        assert rows[1]["path"] == str(song2_path.resolve())


def test_scan_corrupt_files_logged_and_continued(
    synthetic_music_library: Path, tmp_path: Path
) -> None:
    """Verify that corrupt audio files are recorded as errors without halting scanning."""
    db_path = tmp_path / "vibeplay.db"
    corrupt_file = synthetic_music_library / "corrupt.mp3"
    corrupt_file.write_bytes(b"garbage not an mp3 file content")

    summary = scan_directory(synthetic_music_library, db_path)
    assert summary.new == 2
    assert summary.errors == 1
    assert summary.total_processed == 3


def test_cli_scan_command(synthetic_music_library: Path, tmp_path: Path) -> None:
    """Verify that vibeplay scan CLI command runs and outputs summary."""
    db_path = tmp_path / "cli_test.db"
    result = runner.invoke(
        app, ["scan", str(synthetic_music_library), "--db", str(db_path)]
    )

    assert result.exit_code == 0
    assert "Scan Summary" in result.stdout
    assert "New" in result.stdout
    assert "Total Processed" in result.stdout


def test_extract_metadata(synthetic_music_library: Path) -> None:
    """Verify that extract_metadata correctly reads tags from audio files."""
    from vibeplay.scanner import extract_metadata

    song1_path = synthetic_music_library / "Artist1" / "Album1" / "song1.wav"
    metadata_1 = extract_metadata(song1_path)

    assert metadata_1.title == "First Track"
    assert metadata_1.artist == "Artist One"
    assert metadata_1.album == "Album One"
    assert metadata_1.track_no == 1
    assert metadata_1.track_total == 10
    assert metadata_1.year == 2023
    assert metadata_1.genre == "Ambient"
    assert metadata_1.has_cover is True
    assert metadata_1.duration is not None
    assert metadata_1.bitrate is not None

    song2_path = synthetic_music_library / "Artist2" / "Album2" / "song2.wav"
    metadata_2 = extract_metadata(song2_path)

    assert metadata_2.title == "Second Track"
    assert metadata_2.artist == "Artist Two"
    assert metadata_2.album == "Album Two"
    assert metadata_2.track_no == 2
    assert metadata_2.track_total == 10
    assert metadata_2.year == 2024
    assert metadata_2.genre == "Downtempo"
    assert metadata_2.has_cover is False
    assert metadata_2.duration is not None
    assert metadata_2.bitrate is not None


def test_extract_metadata_invalid_file(tmp_path: Path) -> None:
    """Verify that extract_metadata raises ValueError for invalid audio files."""
    from vibeplay.scanner import extract_metadata

    corrupt_file = tmp_path / "corrupt.wav"
    corrupt_file.write_bytes(b"not a valid audio file")

    with pytest.raises(ValueError, match="Mutagen could not recognize audio format"):
        extract_metadata(corrupt_file)
