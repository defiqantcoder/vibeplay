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
    from jeepney.low_level import Message

    return Message.from_buffer(message.serialise(serial=1)).body


def test_mpris_property_reply_serialization():
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
                "Get", "ss", ("org.mpris.MediaPlayer2.Player", prop),
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
