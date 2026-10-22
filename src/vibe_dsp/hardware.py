"""Dynamic ALSA hardware discovery and USB Audio Class capability probing."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from vibe_dsp.models import AudioEndpoint, AuditReport, CardType

logger = logging.getLogger(__name__)

STANDARD_UNLOCKED_RATES = [
    44100,
    48000,
    88200,
    96000,
    176400,
    192000,
    352800,
    384000,
]


def parse_proc_asound_cards(cards_content: str) -> list[dict[str, Any]]:
    """Parse /proc/asound/cards text into structured card dictionaries.

    Example entry:
     0 [sofhdadsp      ]: sof-hda-dsp - sof-hda-dsp
                          HP-HPEnvyx3602_in_1Laptop14_es0xxx-Type1ProductConfigId-8BF7
     1 [KA15           ]: USB-Audio - FIIO KA15
                          FIIO FIIO KA15 at usb-0000:00:14.0-3, high speed

    Args:
        cards_content: Raw contents of /proc/asound/cards.

    Returns:
        list[dict[str, Any]]: Parsed card metadata dictionaries.
    """
    cards: list[dict[str, Any]] = []
    lines = cards_content.strip().splitlines()

    card_header_pattern = re.compile(r"^\s*(\d+)\s+\[([^\]]+)\]:\s+(.*)$")

    current_card: dict[str, Any] | None = None

    for line in lines:
        match = card_header_pattern.match(line)
        if match:
            if current_card:
                cards.append(current_card)
            c_idx = int(match.group(1))
            c_id = match.group(2).strip()
            rest = match.group(3).strip()
            if " - " in rest:
                c_driver, c_name = rest.split(" - ", 1)
                c_driver = c_driver.strip()
                c_name = c_name.strip()
            else:
                c_driver = rest
                c_name = rest
            current_card = {
                "card_index": c_idx,
                "card_id": c_id,
                "driver": c_driver,
                "card_name": c_name,
                "extra_info": "",
            }
        elif current_card and line.startswith(" "):
            extra = line.strip()
            if current_card["extra_info"]:
                current_card["extra_info"] += " " + extra
            else:
                current_card["extra_info"] = extra

    if current_card:
        cards.append(current_card)

    return cards


def parse_proc_asound_pcm(pcm_content: str) -> list[dict[str, Any]]:
    """Parse /proc/asound/pcm to discover playback PCM device numbers.

    Example entry:
    00-00: HDA Analog (*) :  : playback 1 : capture 1
    00-03: HDMI1 (*) : HDMI 1 : playback 1
    01-00: USB Audio : USB Audio : playback 1

    Args:
        pcm_content: Raw contents of /proc/asound/pcm.

    Returns:
        list[dict[str, Any]]: Playback device definitions with card and dev index.
    """
    devices: list[dict[str, Any]] = []
    for line in pcm_content.splitlines():
        line = line.strip()
        if not line or "playback" not in line:
            continue

        parts = line.split(":", 3)
        if len(parts) >= 2:
            card_dev = parts[0].strip()
            dev_name = parts[1].strip()
            if "-" in card_dev:
                c_str, d_str = card_dev.split("-", 1)
                try:
                    c_idx = int(c_str)
                    d_idx = int(d_str)
                    devices.append(
                        {
                            "card_index": c_idx,
                            "device_index": d_idx,
                            "device_name": dev_name,
                        }
                    )
                except ValueError:
                    continue
    return devices


def parse_usb_stream_capabilities(stream_content: str) -> dict[str, Any]:
    """Parse /proc/asound/cardX/stream0 for supported native sample rates and formats.

    Args:
        stream_content: Contents of stream0 file.

    Returns:
        dict[str, Any]: Parsed rates, formats, bit depths, and channel count.
    """
    rates: set[int] = set()
    formats: set[str] = set()
    bit_depths: set[int] = set()
    channels = 2

    # Extract format lines
    format_matches = re.findall(
        r"Format:\s+([A-Za-z0-9_]+)", stream_content, re.IGNORECASE
    )
    for fmt in format_matches:
        formats.add(fmt.upper())

    # Extract rates lines
    rate_matches = re.findall(r"Rates:\s+([0-9,\s]+)", stream_content, re.IGNORECASE)
    for r_str in rate_matches:
        for single in r_str.split(","):
            s_clean = single.strip()
            if s_clean.isdigit():
                rates.add(int(s_clean))

    # Extract bits lines
    bit_matches = re.findall(r"Bits:\s+(\d+)", stream_content, re.IGNORECASE)
    for b in bit_matches:
        bit_depths.add(int(b))

    # Extract channels lines
    chan_matches = re.findall(r"Channels:\s+(\d+)", stream_content, re.IGNORECASE)
    if chan_matches:
        channels = max(int(c) for c in chan_matches)

    # If bits not explicitly given, infer from formats
    if not bit_depths and formats:
        for fmt in formats:
            if "32" in fmt:
                bit_depths.add(32)
            elif "24" in fmt:
                bit_depths.add(24)
            elif "16" in fmt:
                bit_depths.add(16)

    return {
        "rates": sorted(rates),
        "formats": sorted(formats),
        "bit_depths": sorted(bit_depths),
        "channels": channels,
    }


def scan_hardware(procfs_root: Path | None = None) -> AuditReport:
    """Dynamically scan ALSA procfs and hardware endpoints.

    Prioritizes connected USB Audio Class 1.0/2.0 DACs, identifies HDMI and
    speaker fallback endpoints, and gathers native hardware sample rate capabilities.

    Args:
        procfs_root: Path to procfs asound directory (defaults to /proc/asound).

    Returns:
        AuditReport: Complete hardware inventory and recommended bit-perfect endpoint.
    """
    resolved_root = procfs_root or Path("/proc/asound")
    endpoints: list[AudioEndpoint] = []
    cards_file = resolved_root / "cards"
    pcm_file = resolved_root / "pcm"

    if not cards_file.exists():
        logger.warning(
            "Procfs path '%s' not accessible; returning empty audit report",
            cards_file,
        )
        return AuditReport()

    try:
        cards_content = cards_file.read_text(encoding="utf-8", errors="replace")
    except Exception as err:
        logger.error("Failed to read %s: %s", cards_file, err)
        return AuditReport()

    parsed_cards = parse_proc_asound_cards(cards_content)

    pcm_devices: list[dict[str, Any]] = []
    if pcm_file.exists():
        try:
            pcm_content = pcm_file.read_text(encoding="utf-8", errors="replace")
            pcm_devices = parse_proc_asound_pcm(pcm_content)
        except Exception as err:
            logger.warning("Could not read %s: %s", pcm_file, err)

    for card in parsed_cards:
        c_idx = card["card_index"]
        c_id = card["card_id"]
        c_driver = card["driver"]
        c_name = card["card_name"]
        card_dir = resolved_root / f"card{c_idx}"

        # Probe USB identifiers
        usb_id_file = card_dir / "usbid"
        usb_bus_file = card_dir / "usbbus"
        usb_id = usb_id_file.read_text().strip() if usb_id_file.exists() else None
        usb_bus = usb_bus_file.read_text().strip() if usb_bus_file.exists() else None

        is_usb_class = bool(
            usb_id
            or usb_bus
            or c_driver.lower() == "usb-audio"
            or "usb" in card["extra_info"].lower()
        )

        # Find playback device numbers for this card
        card_pcms = [p for p in pcm_devices if p["card_index"] == c_idx]
        if not card_pcms:
            # Default to device 0
            card_pcms = [{"device_index": 0, "device_name": c_name}]

        for pcm in card_pcms:
            dev_idx = pcm["device_index"]
            dev_name = pcm["device_name"] or c_name

            # Probe stream capabilities for USB devices
            rates: list[int] = []
            formats: list[str] = []
            bit_depths: list[int] = []
            channels = 2

            if is_usb_class:
                # Check stream0, stream1, etc.
                stream_files = sorted(card_dir.glob("stream*"))
                if stream_files:
                    try:
                        stream_text = stream_files[0].read_text(
                            encoding="utf-8", errors="replace"
                        )
                        caps = parse_usb_stream_capabilities(stream_text)
                        rates = caps["rates"]
                        formats = caps["formats"]
                        bit_depths = caps["bit_depths"]
                        channels = caps["channels"]
                    except Exception as err:
                        logger.warning(
                            "Could not parse stream capabilities for card %d: %s",
                            c_idx,
                            err,
                        )

                # Fallback rates if stream probing yielded nothing
                if not rates:
                    rates = [44100, 48000, 88200, 96000, 176400, 192000, 384000]
                if not bit_depths:
                    bit_depths = [16, 24, 32]
                if not formats:
                    formats = ["S16_LE", "S24_3LE", "S32_LE"]

                card_type = CardType.USB_DAC
                # Connected USB DAC gets highest priority
                priority = 100
                # Extra bonus for ultra-high sample rate capability
                if max(rates, default=0) >= 384000:
                    priority += 10
            elif "hdmi" in dev_name.lower() or "hdmi" in c_name.lower():
                card_type = CardType.HDMI
                rates = [44100, 48000, 88200, 96000, 192000]
                bit_depths = [16, 24]
                formats = ["S16_LE", "S24_LE"]
                priority = 40
            else:
                card_type = CardType.SPEAKER_ANALOG
                rates = [44100, 48000, 96000]
                bit_depths = [16, 24]
                formats = ["S16_LE", "S24_LE"]
                priority = 20

            # Derive node name pattern
            node_name = (
                f"alsa_output.usb-{c_id}.analog-stereo"
                if card_type == CardType.USB_DAC
                else f"alsa_output.pci-{c_id}.analog-stereo"
            )

            endpoint = AudioEndpoint(
                card_index=c_idx,
                device_index=dev_idx,
                card_id=c_id,
                card_name=c_name,
                driver=c_driver,
                device_name=dev_name,
                card_type=card_type,
                usb_id=usb_id,
                usb_bus=usb_bus,
                rates=rates,
                formats=formats,
                bit_depths=bit_depths,
                channels=channels,
                is_connected=True,
                priority_score=priority,
                pipewire_node_name=node_name,
            )
            endpoints.append(endpoint)

    # Sort endpoints by priority descending
    endpoints.sort(key=lambda ep: ep.priority_score, reverse=True)

    # Prioritize connected USB DAC
    usb_dacs = [ep for ep in endpoints if ep.card_type == CardType.USB_DAC]
    active_dac = usb_dacs[0] if usb_dacs else None

    # Fallback to speakers/headphones if no DAC is plugged in
    speakers = [ep for ep in endpoints if ep.card_type == CardType.SPEAKER_ANALOG]
    hdmi = [ep for ep in endpoints if ep.card_type == CardType.HDMI]

    fallback = speakers[0] if speakers else (hdmi[0] if hdmi else None)

    return AuditReport(
        endpoints=endpoints,
        active_dac=active_dac,
        fallback_endpoint=fallback,
        unlocked_rates=STANDARD_UNLOCKED_RATES,
    )
