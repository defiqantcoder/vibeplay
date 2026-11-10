import os
import pytest
from pathlib import Path
from vibeplay.desktop.mime import parse_desktop_uri, classify_mime_target, parse_m3u_playlist, MimeOpenTarget
from vibeplay.desktop.security import PathTraversalError

def test_parse_desktop_uri_valid_file_path(tmp_path, monkeypatch):
    """Test parse_desktop_uri with a valid absolute file path."""
    media_file = tmp_path / "song.mp3"
    media_file.touch()
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    parsed = parse_desktop_uri(str(media_file))
    assert parsed == media_file

def test_parse_desktop_uri_valid_file_uri(tmp_path, monkeypatch):
    """Test parse_desktop_uri with a valid file:// URI."""
    media_file = tmp_path / "song.mp3"
    media_file.touch()
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    parsed = parse_desktop_uri(f"file://{media_file}")
    assert parsed == media_file

def test_parse_desktop_uri_percent_encoded(tmp_path, monkeypatch):
    """Test parse_desktop_uri with a percent-encoded file:// URI."""
    media_file = tmp_path / "my song.mp3"
    media_file.touch()
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    # %20 for space
    uri = f"file://{tmp_path}/my%20song.mp3"
    parsed = parse_desktop_uri(uri)
    assert parsed == media_file

def test_parse_desktop_uri_null_byte():
    """Test that parse_desktop_uri rejects paths with null bytes."""
    with pytest.raises((ValueError, PathTraversalError)):
        parse_desktop_uri("/home/user/song\x00.mp3")

def test_parse_desktop_uri_path_traversal(tmp_path, monkeypatch):
    """Test that parse_desktop_uri rejects path traversal attempts outside allowed roots."""
    # Set allowed root to tmp_path/allowed
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(allowed_root))

    # Create a file outside allowed roots
    outside_file = tmp_path / "outside.mp3"
    outside_file.touch()

    with pytest.raises((ValueError, PathTraversalError)):
        parse_desktop_uri(str(outside_file))

def test_classify_mime_target_audio(tmp_path, monkeypatch):
    """Test classify_mime_target with valid audio files."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    for ext in [".flac", ".mp3", ".wav"]:
        f = tmp_path / f"test{ext}"
        f.touch()
        target = classify_mime_target(f)
        assert target.target_type == "audio"
        assert target.exists is True

def test_classify_mime_target_playlist(tmp_path, monkeypatch):
    """Test classify_mime_target with valid playlist files."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    for ext in [".m3u", ".m3u8"]:
        f = tmp_path / f"playlist{ext}"
        f.touch()
        target = classify_mime_target(f)
        assert target.target_type == "playlist"
        assert target.exists is True

def test_classify_mime_target_directory(tmp_path, monkeypatch):
    """Test classify_mime_target with a directory."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    sub_dir = tmp_path / "music_folder"
    sub_dir.mkdir()
    target = classify_mime_target(sub_dir)
    assert target.target_type == "directory"
    assert target.exists is True

def test_classify_mime_target_unsupported(tmp_path, monkeypatch):
    """Test classify_mime_target with unsupported file extensions."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    f = tmp_path / "document.txt"
    f.touch()
    target = classify_mime_target(f)
    assert target.target_type == "unsupported"
    assert target.exists is True

def test_parse_m3u_playlist(tmp_path, monkeypatch):
    """Test parse_m3u_playlist parsing various elements."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    # Create some audio files in tmp_path
    track1 = tmp_path / "track1.mp3"
    track1.touch()
    track2 = tmp_path / "track2.flac"
    track2.touch()
    track_rel = tmp_path / "track_rel.wav"
    track_rel.touch()

    # M3U file
    m3u_file = tmp_path / "playlist.m3u8"
    content = f"""#EXTM3U
#EXTINF:233,Artist - Title
{track1}

# Blank line above
file://{track2}
track_rel.wav
#EXTINF:100,Unknown - Unsupported
unsupported.txt
#EXTINF:100,Unknown - Nonexistent
nonexistent.mp3
"""
    m3u_file.write_text(content, encoding="utf-8")

    tracks = parse_m3u_playlist(m3u_file)

    # Expecting: track1 (abs), track2 (uri), track_rel (relative)
    # Excludes: comment lines, blank lines, unsupported extensions, nonexistent files
    assert len(tracks) == 3
    assert tracks[0] == track1
    assert tracks[1] == track2
    assert tracks[2] == track_rel


def test_parse_desktop_uri_empty():
    """Test that parse_desktop_uri rejects empty paths."""
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_desktop_uri("")
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_desktop_uri("   ")

def test_parse_desktop_uri_unsupported_scheme():
    """Test that parse_desktop_uri rejects unsupported schemes."""
    with pytest.raises(ValueError, match="only local 'file://' URIs are allowed"):
        parse_desktop_uri("http://example.com/song.mp3")

def test_parse_desktop_uri_remote_host():
    """Test that parse_desktop_uri rejects remote hosts in file:// URIs."""
    with pytest.raises(ValueError, match="Remote file URI host .* is not allowed"):
        parse_desktop_uri("file://remotehost/song.mp3")

def test_classify_mime_target_file_uri(tmp_path, monkeypatch):
    """Test classify_mime_target with a file:// URI."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    f = tmp_path / "song.mp3"
    f.touch()

    # Use file URI
    target = classify_mime_target(f"file://{f}")
    assert target.target_type == "audio"
    assert target.exists is True

def test_classify_mime_target_path_traversal(tmp_path, monkeypatch):
    """Test classify_mime_target handles path traversal attempts."""
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(allowed_root))

    outside_file = tmp_path / "outside.mp3"
    outside_file.touch()

    with pytest.raises((ValueError, PathTraversalError)):
        classify_mime_target(outside_file)

def test_parse_m3u_playlist_nonexistent():
    """Test parse_m3u_playlist returns empty list for nonexistent playlist."""
    assert parse_m3u_playlist(Path("/nonexistent/playlist.m3u")) == []

def test_parse_m3u_playlist_with_invalid_characters(tmp_path, monkeypatch):
    """Test parse_m3u_playlist ignores lines with null bytes."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    m3u_file = tmp_path / "playlist.m3u"

    track1 = tmp_path / "track1.mp3"
    track1.touch()

    # Create invalid track path with null byte
    content = f"""{track1}
track2\x00.mp3
"""
    m3u_file.write_text(content, encoding="utf-8")

    tracks = parse_m3u_playlist(m3u_file)
    assert len(tracks) == 1
    assert tracks[0] == track1

def test_parse_m3u_playlist_unsupported_uri(tmp_path, monkeypatch):
    """Test parse_m3u_playlist handles unsupported URIs by skipping them."""
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(tmp_path))

    m3u_file = tmp_path / "playlist.m3u"

    track1 = tmp_path / "track1.mp3"
    track1.touch()

    content = f"""{track1}
http://example.com/stream.mp3
"""
    m3u_file.write_text(content, encoding="utf-8")

    tracks = parse_m3u_playlist(m3u_file)
    assert len(tracks) == 1
    assert tracks[0] == track1

def test_parse_m3u_playlist_path_traversal(tmp_path, monkeypatch):
    """Test parse_m3u_playlist skips paths outside allowed roots."""
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    monkeypatch.setenv("VIBEPLAY_EXTRA_MEDIA_ROOTS", str(allowed_root))

    m3u_file = allowed_root / "playlist.m3u"

    track_allowed = allowed_root / "track.mp3"
    track_allowed.touch()

    track_outside = tmp_path / "outside.mp3"
    track_outside.touch()

    content = f"""{track_allowed}
{track_outside}
../outside.mp3
"""
    m3u_file.write_text(content, encoding="utf-8")

    tracks = parse_m3u_playlist(m3u_file)
    assert len(tracks) == 1
    assert tracks[0] == track_allowed
