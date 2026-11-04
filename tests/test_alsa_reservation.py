from __future__ import annotations

import pytest

from vibeplay.hardware import AudioEndpointInfo
from vibeplay.alsa_reservation import generate_bitperfect_output_config

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
    assert "dop" not in config.split("mixer_type")[0] # Check dop is not before mixer_type for the ALSA block
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
