import pytest
from unittest.mock import patch

from vibeplay.hardware import discover_audio_endpoints

def test_audio_endpoints_discovery(mocker):
    mocker.patch('vibeplay.hardware.Path.read_text', return_value="mock card")
    mocker.patch('vibeplay.hardware.Path.exists', return_value=True)
    mocker.patch('vibeplay.hardware.Path.is_dir', return_value=True)
    mocker.patch('vibeplay.hardware.Path.iterdir', return_value=[])
    endpoints = discover_audio_endpoints()
    assert isinstance(endpoints, list)
