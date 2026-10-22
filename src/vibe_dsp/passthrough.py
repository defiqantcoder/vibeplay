"""Receiver bitstream passthrough configuration for HDMI and optical S/PDIF multichannel audio."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibe_dsp.backup import create_backup
from vibe_dsp.models import AudioEndpoint, CardType
from vibe_dsp.hardware import scan_hardware

logger = logging.getLogger(__name__)

# Standard bitstream passthrough codec mapping
CODEC_MAP: dict[str, str] = {
    "ac3": "ac3-iec61937",
    "eac3": "eac3-iec61937",
    "truehd": "truehd-iec61937",
    "dts": "dts-iec61937",
    "dts-hd": "dtshd-iec61937",
    "dtshd": "dtshd-iec61937",
    "aac": "aac-iec61937",
}

# Standard human-readable descriptions
CODEC_DESCRIPTIONS: dict[str, str] = {
    "ac3": "Dolby Digital (AC3 5.1 / IEC61937)",
    "eac3": "Dolby Digital Plus / E-AC-3 Atmos",
    "truehd": "Dolby TrueHD (Lossless Multichannel Bitstream)",
    "dts": "DTS Digital Surround (5.1 Bitstream)",
    "dts-hd": "DTS-HD Master Audio / High Resolution",
    "aac": "MPEG-4 AAC Multichannel Bitstream",
}


@dataclass
class ReceiverEndpoint:
    """Multichannel AV receiver or HDMI/SPDIF audio sink."""

    sink_id: str
    sink_name: str
    description: str
    is_hdmi: bool = True
    is_spdif: bool = False
    is_default: bool = False
    supported_codecs: list[str] = field(default_factory=list)
    active_codecs: list[str] = field(default_factory=list)
    raw_formats: list[str] = field(default_factory=list)


def query_pactl_sinks() -> list[ReceiverEndpoint]:
    """Query audio sinks and passthrough format capabilities via pactl.

    Returns:
        list[ReceiverEndpoint]: List of detected digital receiver endpoints.
    """
    if not shutil.which("pactl"):
        logger.debug("pactl command not available")
        return []

    try:
        proc = subprocess.run(
            ["pactl", "list", "sinks"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if proc.returncode != 0:
            logger.warning("pactl list sinks returned code %d: %s", proc.returncode, proc.stderr)
            return []
        return parse_pactl_sinks_output(proc.stdout)
    except Exception as err:
        logger.warning("Failed to query pactl sinks: %s", err)
        return []


def parse_pactl_sinks_output(output: str) -> list[ReceiverEndpoint]:
    """Parse pactl list sinks stdout into structured ReceiverEndpoint models.

    Args:
        output: Raw text output from pactl list sinks.

    Returns:
        list[ReceiverEndpoint]: Parsed endpoints.
    """
    endpoints: list[ReceiverEndpoint] = []
    # Sinks are separated by "Sink #"
    blocks = re.split(r"\n(?=Sink #\d+)", output)

    for block in blocks:
        if not block.strip().startswith("Sink #"):
            continue

        sink_id_match = re.search(r"Sink #(\d+)", block)
        name_match = re.search(r"Name:\s+([^\n]+)", block)
        desc_match = re.search(r"Description:\s+([^\n]+)", block)

        sink_id = sink_id_match.group(1) if sink_id_match else "0"
        sink_name = name_match.group(1).strip() if name_match else f"sink_{sink_id}"
        description = desc_match.group(1).strip() if desc_match else sink_name

        is_hdmi = "hdmi" in sink_name.lower() or "hdmi" in description.lower()
        is_spdif = "iec958" in sink_name.lower() or "spdif" in sink_name.lower() or "optical" in description.lower()

        # Check Formats section
        formats: list[str] = []
        formats_match = re.search(r"Formats:\s*\n((?:\s+[^\n]+\n)+)", block)
        if formats_match:
            fmt_lines = formats_match.group(1).splitlines()
            for line in fmt_lines:
                fmt = line.strip()
                if fmt:
                    formats.append(fmt)

        # Detect supported and active codecs
        supported: list[str] = []
        for c_key, c_fmt in CODEC_MAP.items():
            if any(c_fmt in f.lower() or c_key in f.lower() for f in formats):
                if c_key not in supported and c_key != "dtshd":
                    supported.append(c_key)

        # Default standard bitstream codecs supported by digital HDMI receivers if driver supports IEC61937
        if is_hdmi and not supported:
            supported = ["ac3", "eac3", "dts", "truehd", "dts-hd"]
        elif is_spdif and not supported:
            # S/PDIF optical bandwidth limits to compressed 5.1 AC3 and DTS
            supported = ["ac3", "dts"]

        endpoint = ReceiverEndpoint(
            sink_id=sink_id,
            sink_name=sink_name,
            description=description,
            is_hdmi=is_hdmi,
            is_spdif=is_spdif,
            supported_codecs=supported,
            active_codecs=list(supported),
            raw_formats=formats,
        )
        endpoints.append(endpoint)

    return endpoints


def discover_receiver_endpoints(procfs_root: Path | None = None) -> list[ReceiverEndpoint]:
    """Discover digital multichannel receivers (HDMI & S/PDIF) via pactl and ALSA procfs.

    Args:
        procfs_root: Path to ALSA procfs.

    Returns:
        list[ReceiverEndpoint]: Discovered endpoints.
    """
    pactl_endpoints = query_pactl_sinks()
    # Filter to HDMI and digital outputs
    digital_endpoints = [ep for ep in pactl_endpoints if ep.is_hdmi or ep.is_spdif]

    # If pactl did not report HDMI sinks, check hardware audit
    if not digital_endpoints:
        hw_report = scan_hardware(procfs_root=procfs_root)
        hdmi_cards = [ep for ep in hw_report.endpoints if ep.card_type == CardType.HDMI]
        for idx, card in enumerate(hdmi_cards):
            digital_endpoints.append(
                ReceiverEndpoint(
                    sink_id=str(idx),
                    sink_name=f"alsa_output.{card.card_id}.hdmi-surround",
                    description=f"{card.card_name} HDMI Audio Output ({card.hw_device})",
                    is_hdmi=True,
                    is_spdif=False,
                    supported_codecs=["ac3", "eac3", "dts", "truehd", "dts-hd"],
                    active_codecs=["ac3", "eac3", "dts", "truehd", "dts-hd"],
                )
            )

    return digital_endpoints


def configure_sink_passthrough(
    sink_name_or_id: str,
    selected_codecs: list[str],
    set_as_default: bool = True,
) -> tuple[bool, str]:
    """Configure raw bitstream passthrough formats on a target sink via pactl.

    Args:
        sink_name_or_id: Target sink identifier or name.
        selected_codecs: List of codec keys (e.g. ['ac3', 'eac3', 'truehd', 'dts', 'dts-hd']).
        set_as_default: Whether to set this sink as default audio output.

    Returns:
        tuple[bool, str]: Success boolean and descriptive status message.
    """
    if not shutil.which("pactl"):
        return False, "pactl binary not found in PATH"

    # Always include standard PCM
    format_list = ["pcm"]
    for codec in selected_codecs:
        c_clean = codec.lower().strip()
        iec_fmt = CODEC_MAP.get(c_clean, c_clean)
        if iec_fmt not in format_list:
            format_list.append(iec_fmt)

    formats_arg = ", ".join(format_list)
    logger.info("Setting sink %s formats to: %s", sink_name_or_id, formats_arg)

    try:
        res = subprocess.run(
            ["pactl", "set-sink-formats", str(sink_name_or_id), formats_arg],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if res.returncode != 0:
            return False, f"pactl set-sink-formats failed ({res.returncode}): {res.stderr.strip()}"

        if set_as_default:
            subprocess.run(
                ["pactl", "set-default-sink", str(sink_name_or_id)],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )

        return True, f"Configured passthrough for [{', '.join(selected_codecs)}] on sink {sink_name_or_id}"
    except Exception as err:
        logger.warning("Error configuring sink passthrough: %s", err)
        return False, str(err)
