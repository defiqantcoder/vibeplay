
from vibeplay.alsa_reservation import check_alsa_device_status


def test_check_alsa_device_status_closed(monkeypatch):
    monkeypatch.setattr('vibeplay.alsa_reservation.Path.exists', lambda self: True)
    monkeypatch.setattr('vibeplay.alsa_reservation.Path.read_text', lambda self, encoding="utf-8", errors="replace": "closed\n")

    assert check_alsa_device_status(0, 0) == "closed"

def test_check_alsa_device_status_running(monkeypatch):
    monkeypatch.setattr('vibeplay.alsa_reservation.Path.exists', lambda self: True)
    monkeypatch.setattr('vibeplay.alsa_reservation.Path.read_text', lambda self, encoding="utf-8", errors="replace": "RUNNING\n")

    assert check_alsa_device_status(1, 1) == "RUNNING"

def test_check_alsa_device_status_file_not_found(monkeypatch):
    monkeypatch.setattr('vibeplay.alsa_reservation.Path.exists', lambda self: False)

    assert check_alsa_device_status(0, 0) == "unknown"

def test_check_alsa_device_status_read_error(monkeypatch):
    monkeypatch.setattr('vibeplay.alsa_reservation.Path.exists', lambda self: True)

    def raise_err(*args, **kwargs):
        raise PermissionError("Denied")

    monkeypatch.setattr('vibeplay.alsa_reservation.Path.read_text', raise_err)

    assert check_alsa_device_status(0, 0) == "unknown"
