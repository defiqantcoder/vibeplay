from __future__ import annotations

import pytest

from vibeplay.alsa_reservation import check_alsa_device_status, generate_bitperfect_output_config
from vibeplay.hardware import AudioEndpointInfo


def test_check_alsa_device_status_closed(monkeypatch):
    monkeypatch.setattr("vibeplay.alsa_reservation.Path.exists", lambda self: True)
    monkeypatch.setattr(
        "vibeplay.alsa_reservation.Path.read_text",
        lambda self, encoding="utf-8", errors="replace": "closed\n",
    )
    assert check_alsa_device_status(0, 0) == "closed"


def test_check_alsa_device_status_running(monkeypatch):
    monkeypatch.setattr("vibeplay.alsa_reservation.Path.exists", lambda self: True)
    monkeypatch.setattr(
        "vibeplay.alsa_reservation.Path.read_text",
        lambda self, encoding="utf-8", errors="replace": "RUNNING\n",
    )
    assert check_alsa_device_status(1, 1) == "RUNNING"


def test_check_alsa_device_status_file_not_found(monkeypatch):
    monkeypatch.setattr("vibeplay.alsa_reservation.Path.exists", lambda self: False)
    assert check_alsa_device_status(0, 0) == "unknown"


def test_check_alsa_device_status_read_error(monkeypatch):
    monkeypatch.setattr("vibeplay.alsa_reservation.Path.exists", lambda self: True)

    def raise_err(*args, **kwargs):
        raise PermissionError("Denied")

    monkeypatch.setattr("vibeplay.alsa_reservation.Path.read_text", raise_err)
    assert check_alsa_device_status(0, 0) == "unknown"


@pytest.fixture
def standard_dac() -> AudioEndpointInfo:
    return AudioEndpointInfo(
        card_index=1,
        card_id="StandardDAC",
        card_name="Standard USB DAC",
        driver="usb-audio",
        is_usb_dac=True,
        hw_device="hw:1,0",
        plughw_device="plughw:1,0",
        supported_rates=[44100, 48000, 96000, 192000],
        supported_formats=["S16_LE", "S24_LE", "S32_LE"],
    )


@pytest.fixture
def dsd_dac() -> AudioEndpointInfo:
    return AudioEndpointInfo(
        card_index=2,
        card_id="DSDDAC",
        card_name="DSD Capable DAC",
        driver="usb-audio",
        is_usb_dac=True,
        hw_device="hw:2,0",
        plughw_device="plughw:2,0",
        supported_rates=[44100, 48000, 96000, 192000, 384000, 768000],
        supported_formats=["S16_LE", "S24_LE", "S32_LE", "DSD_U32_BE"],
    )


def test_generate_bitperfect_output_config_standard(standard_dac: AudioEndpointInfo):
    """Test generation without DSD support and with PipeWire fallback."""
    config = generate_bitperfect_output_config(standard_dac, pipewire_fallback=True)

    assert "Target: Standard USB DAC (hw:1,0)" in config
    assert 'name            "Bit-Perfect ALSA [Direct] (Standard USB DAC)"' in config
    assert 'device          "hw:1,0"' in config
    assert 'name            "Bit-Perfect ALSA [Plug Fallback] (Standard USB DAC)"' in config
    assert 'device          "plughw:1,0"' in config
    assert "dop" not in config.split("mixer_type")[0]
    assert 'type            "pipewire"' in config


def test_generate_bitperfect_output_config_dsd(dsd_dac: AudioEndpointInfo):
    """Test generation with DSD support."""
    config = generate_bitperfect_output_config(dsd_dac, pipewire_fallback=True)

    assert 'dop             "yes"' in config
    assert "Target: DSD Capable DAC (hw:2,0)" in config


def test_generate_bitperfect_output_config_no_fallback(standard_dac: AudioEndpointInfo):
    """Test generation without PipeWire fallback."""
    config = generate_bitperfect_output_config(standard_dac, pipewire_fallback=False)

    assert 'type            "pipewire"' not in config
    assert 'type            "alsa"' in config
