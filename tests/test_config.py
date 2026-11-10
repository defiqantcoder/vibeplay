"""Tests for vibeplay configuration module."""

import os
from unittest import mock

import pytest

from vibeplay.config import Settings, get_settings


def test_get_settings_loads_from_env() -> None:
    """Verify that get_settings correctly loads configuration from environment variables."""
    # Ensure cache is clear before testing
    get_settings.cache_clear()

    # Define environment variables to patch
    env_vars = {
        "VIBEPLAY_ENV": "testing_env",
        "LOG_LEVEL": "DEBUG",
    }

    # Patch os.environ and verify settings
    with mock.patch.dict(os.environ, env_vars, clear=False):
        settings = get_settings()
        assert settings.vibeplay_env == "testing_env"
        assert settings.log_level == "DEBUG"

    # Clear cache again so other tests are not affected
    get_settings.cache_clear()


@pytest.mark.parametrize("candidate_index", range(4))
def test_unconfigured_music_directory_preserves_mpd_detection_order(tmp_path, monkeypatch, candidate_index):
    from vibeplay.player import _ensure_mpd_symlink

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MUSIC_DIRECTORY", raising=False)
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    candidates = [tmp_path / "music-test", tmp_path / "Music", tmp_path / ".local/share/vibeplay/music", working_dir]
    for candidate in candidates[candidate_index:]:
        candidate.mkdir(parents=True, exist_ok=True)
    track = tmp_path / "external.flac"
    track.touch()
    settings = Settings(_env_file=None)

    assert settings.music_directory is None
    assert settings.music_dir is None
    assert _ensure_mpd_symlink(track, settings=settings) == ".vibeplay_symlinks/external.flac"
    assert (candidates[candidate_index] / ".vibeplay_symlinks/external.flac").resolve() == track
    for candidate in candidates[candidate_index + 1:]:
        assert not (candidate / ".vibeplay_symlinks").exists()


@pytest.mark.parametrize("source", ["environment", "constructor"])
def test_configured_music_directory_takes_priority(tmp_path, monkeypatch, source):
    from vibeplay.player import _ensure_mpd_symlink

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MUSIC_DIRECTORY", raising=False)
    configured = tmp_path / "configured"
    configured.mkdir()
    fallback = tmp_path / "music-test"
    fallback.mkdir()
    track = tmp_path / "external.flac"
    track.touch()
    if source == "environment":
        monkeypatch.setenv("MUSIC_DIRECTORY", str(configured))
        settings = Settings(_env_file=None)
    else:
        settings = Settings(_env_file=None, music_directory=configured)

    assert settings.music_directory == configured
    assert settings.music_dir == configured
    assert _ensure_mpd_symlink(track, settings=settings) == ".vibeplay_symlinks/external.flac"
    assert (configured / ".vibeplay_symlinks/external.flac").resolve() == track
    assert not (fallback / ".vibeplay_symlinks").exists()
