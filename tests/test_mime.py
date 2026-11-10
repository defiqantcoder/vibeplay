from pathlib import Path
from tempfile import TemporaryDirectory

from vibeplay.desktop.mime import parse_m3u_playlist


def test_parse_m3u_playlist_valid_relative(tmp_path):
    playlist_file = tmp_path / "valid.m3u"

    track1 = tmp_path / "track1.flac"
    track1.touch()

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    track2 = subdir / "track2.mp3"
    track2.touch()

    playlist_file.write_text("track1.flac\nsubdir/track2.mp3\n")

    parsed = parse_m3u_playlist(playlist_file)
    assert parsed == [track1, track2]


def test_parse_m3u_playlist_path_traversal(tmp_path):
    playlist_file = tmp_path / "traversal.m3u"

    # Create a secret file outside the tmp_path base (but we simulate traversal attempting to reach it)
    # To test actual traversal rejection via resolve_within, we can attempt to escape tmp_path root

    # We write a playlist with traversal
    playlist_file.write_text("../../secret.flac\n")

    parsed = parse_m3u_playlist(playlist_file)
    # The traversal should fail resolve_within and return empty list
    assert parsed == []


def test_parse_m3u_playlist_absolute_outside_roots(tmp_path, monkeypatch):
    playlist_file = tmp_path / "absolute.m3u"

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", raising=False)
    with TemporaryDirectory() as unauthorized_dir:
        unauthorized_file = Path(unauthorized_dir) / "unauthorized.flac"
        unauthorized_file.touch()
        playlist_file.write_text(f"{unauthorized_file}\n")

        assert parse_m3u_playlist(playlist_file) == []


def test_parse_m3u_playlist_relative_escape_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    playlist_dir = tmp_path / "playlists"
    playlist_dir.mkdir()
    track = tmp_path / "outside.flac"
    track.touch()
    playlist_file = playlist_dir / "escape.m3u"
    playlist_file.write_text("../outside.flac\n")

    assert parse_m3u_playlist(playlist_file) == []

    # Absolute entries still allow tracks elsewhere under the home directory.
    playlist_file.write_text(f"{track}\n")
    assert parse_m3u_playlist(playlist_file) == [track]


def test_parse_m3u_playlist_ignores_missing_and_unsupported(tmp_path):
    playlist_file = tmp_path / "mixed.m3u"

    track1 = tmp_path / "track1.flac"
    track1.touch()

    track2 = tmp_path / "image.png"
    track2.touch()

    # missing.flac does not exist

    playlist_file.write_text("track1.flac\nimage.png\nmissing.flac\n")

    parsed = parse_m3u_playlist(playlist_file)
    assert parsed == [track1]
