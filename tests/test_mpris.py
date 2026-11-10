from vibeplay.desktop.mpris import _NO_TRACK_PATH, _format_mpris_metadata, _project_song_metadata


def test_project_song_metadata_nested():
    data = {"current_song": {"id": "123", "artist": "Test Artist", "title": "Test Title", "album": "Test Album", "duration": "123.456"}}
    result = _project_song_metadata(data)
    assert result == {
        "mpris:trackid": "/org/mpris/MediaPlayer2/TrackList/123",
        "xesam:title": "Test Title",
        "xesam:artist": ["Test Artist"],
        "xesam:album": "Test Album",
        "mpris:length": 123456000,
    }


def test_project_song_metadata_flat():
    data = {"id": 456, "artist": "Another Artist", "title": "Another Title", "album": "Another Album", "duration": 60.5}
    result = _project_song_metadata(data)
    assert result == {
        "mpris:trackid": "/org/mpris/MediaPlayer2/TrackList/456",
        "xesam:title": "Another Title",
        "xesam:artist": ["Another Artist"],
        "xesam:album": "Another Album",
        "mpris:length": 60500000,
    }


def test_project_song_metadata_empty():
    assert _project_song_metadata({}) == {}
    assert _project_song_metadata({"status": "offline"}) == {}


def test_project_song_metadata_special_chars():
    data = {"id": "abc-123!@#", "artist": "Special Artist", "title": "Special Title", "album": "Special Album", "duration": "100"}
    result = _project_song_metadata(data)
    assert result["mpris:trackid"] == "/org/mpris/MediaPlayer2/TrackList/abc_123___"


def test_format_mpris_metadata_empty():
    result = _format_mpris_metadata({})
    assert result == {"mpris:trackid": ("o", _NO_TRACK_PATH)}


def test_format_mpris_metadata_populated():
    meta = {
        "mpris:trackid": "/org/mpris/MediaPlayer2/TrackList/789",
        "xesam:title": "A Title",
        "xesam:artist": ["An Artist"],
        "xesam:album": "An Album",
        "mpris:length": 150000000,
    }
    result = _format_mpris_metadata(meta)
    assert result == {
        "mpris:trackid": ("o", "/org/mpris/MediaPlayer2/TrackList/789"),
        "xesam:title": ("s", "A Title"),
        "xesam:artist": ("as", ["An Artist"]),
        "xesam:album": ("s", "An Album"),
        "mpris:length": ("x", 150000000),
    }
