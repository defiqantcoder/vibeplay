from unittest.mock import patch

from vibeplay.desktop.mpris import MPRISServer


class MockRunner:
    def __init__(self):
        self.host = "127.0.0.1"
        self.port = 8080
        self.is_running = True


def test_mpris_server_lifecycle():
    runner = MockRunner()
    server = MPRISServer(runner)

    server.start()
    assert server.is_running

    server.stop()
    assert not server.is_running


def test_mpris_api_post():
    runner = MockRunner()
    server = MPRISServer(runner)

    with patch("vibeplay.desktop.mpris.urlopen") as mock_urlopen:
        server._api_post("/player/toggle")
        mock_urlopen.assert_called_once()


# Exercise real Jeepney marshalling so malformed variant bodies cannot pass.
def _roundtrip(message):
    """Serialize and deserialize a Jeepney message to verify valid D-Bus marshalling."""
    from jeepney.low_level import Message

    return Message.from_buffer(message.serialise(serial=1)).body


def test_mpris_property_reply_serialization():
    """Verify Properties.Get returns valid single-argument variant bodies for PlaybackStatus and Metadata."""
    from unittest.mock import Mock

    from jeepney import DBusAddress, new_method_call

    server = MPRISServer(MockRunner())
    no_track = "/org/mpris/MediaPlayer2/TrackList/NoTrack"
    track = "/org/mpris/MediaPlayer2/TrackList/42"
    for metadata in ({}, {"xesam:title": "Title"}, {"mpris:trackid": track, "xesam:title": "Title"}):
        for prop in ("Metadata", "PlaybackStatus"):
            server.current_metadata = metadata
            server.is_running = True
            request = new_method_call(
                DBusAddress(
                    "/org/mpris/MediaPlayer2", bus_name="org.mpris.MediaPlayer2.vibeplay", interface="org.freedesktop.DBus.Properties"
                ),
                "Get",
                "ss",
                ("org.mpris.MediaPlayer2.Player", prop),
            )
            request.header.serial = 1
            conn = Mock()

            def receive(**kwargs):
                server.is_running = False
                return request

            conn.receive.side_effect = receive
            with patch("jeepney.io.blocking.open_dbus_connection", return_value=conn):
                server._run_dbus()
            conn.send_message.assert_called_once()
            body = _roundtrip(conn.send_message.call_args.args[0])
            if prop == "PlaybackStatus":
                assert body == (("s", "Stopped"),)
            else:
                assert len(body) == 1
                signature, result = body[0]
                assert signature == "a{sv}"
                assert result["mpris:trackid"] == ("o", metadata.get("mpris:trackid", no_track))
                if metadata:
                    assert result["xesam:title"] == ("s", "Title")
                    assert result["xesam:artist"] == ("as", [])
                    assert result["mpris:length"] == ("x", 0)


def test_mpris_properties_changed_serialization():
    """Verify PropertiesChanged emits typed PlaybackStatus and Metadata for nested and empty payloads."""
    import json
    from unittest.mock import Mock

    server = MPRISServer(MockRunner())
    server.conn = Mock()
    song = {"id": 42, "title": "Title", "artist": "Artist", "album": "Album", "duration": 1.5}
    for current_song in (song, None):
        server.is_running = True
        response = Mock(status=200)
        response.read.return_value = json.dumps({"state": "play" if current_song else "stop", "current_song": current_song}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        def sleep(seconds):
            if seconds == 1.0:
                server.is_running = False

        server.conn.reset_mock()
        with patch("vibeplay.desktop.mpris.urlopen", return_value=response), patch("vibeplay.desktop.mpris.time.sleep", side_effect=sleep):
            server._run_poll()
        server.conn.send_message.assert_called_once()
        interface, changed, invalidated = _roundtrip(server.conn.send_message.call_args.args[0])
        assert interface == "org.mpris.MediaPlayer2.Player"
        assert invalidated == []
        assert changed["PlaybackStatus"] == ("s", "Playing" if current_song else "Stopped")
        signature, metadata = changed["Metadata"]
        assert signature == "a{sv}"
        if current_song:
            assert metadata == {
                "mpris:trackid": ("o", "/org/mpris/MediaPlayer2/TrackList/42"),
                "xesam:title": ("s", "Title"),
                "xesam:artist": ("as", ["Artist"]),
                "xesam:album": ("s", "Album"),
                "mpris:length": ("x", 1500000),
            }
        else:
            assert metadata == {"mpris:trackid": ("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}


def test_mpris_flat_status_projection_and_standby_notrack():
    """Verify flat /api/player/status fields emit track metadata while standby placeholder yields NoTrack."""
    import json
    from unittest.mock import Mock

    server = MPRISServer(MockRunner())
    server.conn = Mock()

    # 1. Flat status payload with active track
    flat_active = {
        "state": "play",
        "song_id": "77",
        "track_id": 9,
        "title": "Midnight Tape",
        "artist": "Lo-Fi Duo",
        "album": "Crate Vol. 2",
        "file": "/music/midnight.flac",
        "duration": 2.5,
    }
    server.is_running = True
    resp_active = Mock(status=200)
    resp_active.read.return_value = json.dumps(flat_active).encode()
    resp_active.__enter__ = Mock(return_value=resp_active)
    resp_active.__exit__ = Mock(return_value=False)

    def stop_loop(seconds):
        if seconds == 1.0:
            server.is_running = False

    with patch("vibeplay.desktop.mpris.urlopen", return_value=resp_active), patch("vibeplay.desktop.mpris.time.sleep", side_effect=stop_loop):
        server._run_poll()

    server.conn.send_message.assert_called_once()
    _, changed, _ = _roundtrip(server.conn.send_message.call_args.args[0])
    assert changed["PlaybackStatus"] == ("s", "Playing")
    assert changed["Metadata"] == (
        "a{sv}",
        {
            "mpris:trackid": ("o", "/org/mpris/MediaPlayer2/TrackList/77"),
            "xesam:title": ("s", "Midnight Tape"),
            "xesam:artist": ("as", ["Lo-Fi Duo"]),
            "xesam:album": ("s", "Crate Vol. 2"),
            "mpris:length": ("x", 2500000),
        },
    )

    # 2. Standby placeholder payload (MPD offline, song_id=None, file="") must revert to NoTrack
    standby_payload = {
        "state": "stop",
        "song_id": None,
        "track_id": None,
        "title": "vibeplay Precision Console",
        "artist": "Queue a track or generated playlist",
        "album": "Bit-Perfect Standby",
        "file": "",
        "duration": 0.0,
    }
    server.is_running = True
    server.conn.reset_mock()
    resp_standby = Mock(status=200)
    resp_standby.read.return_value = json.dumps(standby_payload).encode()
    resp_standby.__enter__ = Mock(return_value=resp_standby)
    resp_standby.__exit__ = Mock(return_value=False)

    with patch("vibeplay.desktop.mpris.urlopen", return_value=resp_standby), patch("vibeplay.desktop.mpris.time.sleep", side_effect=stop_loop):
        server._run_poll()

    server.conn.send_message.assert_called_once()
    _, changed_standby, _ = _roundtrip(server.conn.send_message.call_args.args[0])
    assert changed_standby["PlaybackStatus"] == ("s", "Stopped")
    assert changed_standby["Metadata"] == ("a{sv}", {"mpris:trackid": ("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")})
