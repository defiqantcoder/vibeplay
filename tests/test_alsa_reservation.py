from unittest.mock import patch

import pytest

import vibe_dsp.alsa_reservation as dsp_alsa

# We need to test both vibeplay and vibe_dsp versions
import vibeplay.alsa_reservation as vp_alsa
from vibeplay.hardware import AudioEndpointInfo


@pytest.fixture(autouse=True)
def mock_alsa_proc():
    with patch("pathlib.Path.exists") as mock_exists:
        yield mock_exists


def test_check_alsa_device_status_closed():
    # Test vibeplay
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value="closed\n"):
            assert vp_alsa.check_alsa_device_status(1) == "closed"

    # Test vibe_dsp
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value="closed\n"):
            assert dsp_alsa.check_alsa_device_status(1) == "closed"


def test_check_alsa_device_status_running():
    # Test vibeplay
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value="RUNNING\n"):
            assert vp_alsa.check_alsa_device_status(2, 1) == "RUNNING"

    # Test vibe_dsp
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", return_value="RUNNING\n"):
            assert dsp_alsa.check_alsa_device_status(2, 1) == "RUNNING"


def test_check_alsa_device_status_permission_denied():
    # Test vibeplay
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", side_effect=PermissionError):
            assert vp_alsa.check_alsa_device_status(1) == "unknown"

    # Test vibe_dsp
    with patch("pathlib.Path.exists", return_value=True):
        with patch("pathlib.Path.read_text", side_effect=PermissionError):
            assert dsp_alsa.check_alsa_device_status(1) == "unknown"


def test_check_alsa_device_status_not_exists():
    # Test vibeplay
    with patch("pathlib.Path.exists", return_value=False):
        assert vp_alsa.check_alsa_device_status(1) == "unknown"

    # Test vibe_dsp
    with patch("pathlib.Path.exists", return_value=False):
        assert dsp_alsa.check_alsa_device_status(1) == "unknown"


def test_generate_bitperfect_output_config_no_dsd():
    endpoint = AudioEndpointInfo(
        card_index=1,
        card_id="TEST",
        card_name="Test Card",
        driver="test",
        hw_device="hw:1,0",
        plughw_device="plughw:1,0",
        supported_formats=["S16_LE", "S32_LE"],
    )

    config = vp_alsa.generate_bitperfect_output_config(endpoint)
    assert 'dop             "yes"' not in config
    assert 'device          "hw:1,0"' in config


def test_generate_bitperfect_output_config_with_dsd():
    endpoint = AudioEndpointInfo(
        card_index=1,
        card_id="TEST",
        card_name="Test Card",
        driver="test",
        hw_device="hw:1,0",
        plughw_device="plughw:1,0",
        supported_formats=["S16_LE", "S32_LE", "DSD_U32_BE"],
    )

    config = vp_alsa.generate_bitperfect_output_config(endpoint)
    assert 'dop             "yes"' in config
    assert 'device          "hw:1,0"' in config
