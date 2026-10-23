"""Unit and integration tests for receiver bitstream passthrough (Phase 5.4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vibe_dsp.passthrough import (
    CODEC_DESCRIPTIONS,
    CODEC_MAP,
    ReceiverEndpoint,
    configure_sink_passthrough,
    discover_receiver_endpoints,
    parse_pactl_sinks_output,
)

SAMPLE_PACTL_OUTPUT = """
Sink #42
	State: RUNNING
	Name: alsa_output.pci-0000_00_1f.3.analog-stereo
	Description: Built-in Audio Analog Stereo
	Driver: PipeWire
	Formats:
		pcm

Sink #43
	State: SUSPENDED
	Name: alsa_output.pci-0000_01_00.1.hdmi-surround-extra1
	Description: GA106 High Definition Audio Controller Digital Surround 5.1 (HDMI 2)
	Driver: PipeWire
	Formats:
		pcm
		ac3-iec61937
		eac3-iec61937
		dts-iec61937
		truehd-iec61937
		dtshd-iec61937

Sink #44
	State: SUSPENDED
	Name: alsa_output.usb-FIIO_KA15.iec958-stereo
	Description: FIIO KA15 Digital Stereo (S/PDIF)
	Driver: PipeWire
	Formats:
		pcm
		ac3-iec61937
		dts-iec61937
"""


def test_parse_pactl_sinks_output() -> None:
    """Verify parsing pactl list sinks for HDMI and SPDIF endpoints."""
    endpoints = parse_pactl_sinks_output(SAMPLE_PACTL_OUTPUT)
    assert len(endpoints) == 3

    # Analog sink
    analog = endpoints[0]
    assert analog.is_hdmi is False
    assert analog.is_spdif is False

    # HDMI sink
    hdmi = endpoints[1]
    assert hdmi.is_hdmi is True
    assert "ac3" in hdmi.supported_codecs
    assert "eac3" in hdmi.supported_codecs
    assert "truehd" in hdmi.supported_codecs
    assert "dts" in hdmi.supported_codecs
    assert "dts-hd" in hdmi.supported_codecs

    # SPDIF sink
    spdif = endpoints[2]
    assert spdif.is_spdif is True
    assert "ac3" in spdif.supported_codecs
    assert "dts" in spdif.supported_codecs


def test_codec_mapping_and_descriptions() -> None:
    """Verify IEC61937 format strings and human descriptions."""
    assert CODEC_MAP["ac3"] == "ac3-iec61937"
    assert CODEC_MAP["truehd"] == "truehd-iec61937"
    assert "Dolby TrueHD" in CODEC_DESCRIPTIONS["truehd"]
    assert "DTS-HD" in CODEC_DESCRIPTIONS["dts-hd"]


def test_configure_sink_passthrough() -> None:
    """Verify configure_sink_passthrough executes pactl set-sink-formats."""
    with patch("shutil.which", return_value="/usr/bin/pactl"), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        success, msg = configure_sink_passthrough(
            sink_name_or_id="alsa_output.hdmi-surround",
            selected_codecs=["ac3", "truehd", "dts-hd"],
            set_as_default=True,
        )

        assert success is True
        assert "Configured passthrough" in msg

        # Ensure pactl set-sink-formats was invoked with pcm and selected IEC formats
        mock_run.assert_any_call(
            ["pactl", "set-sink-formats", "alsa_output.hdmi-surround", "pcm, ac3-iec61937, truehd-iec61937, dtshd-iec61937"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        # Ensure default sink was set
        mock_run.assert_any_call(
            ["pactl", "set-default-sink", "alsa_output.hdmi-surround"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
