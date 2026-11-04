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
