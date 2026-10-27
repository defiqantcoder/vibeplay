"""Smart DAC discoverability, hardware probing, and dynamic audio output management.

Enables pure bit-perfect ALSA hardware routing, detects USB DACs and audio endpoints,
and dynamically switches active playback between connected devices.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STANDARD_RATES = [
    44100,
    48000,
    88200,
    96000,
    176400,
    192000,
    352800,
    384000,
    768000,
]


@dataclass
class AudioEndpointInfo:
    """Represents a discovered audio endpoint (ALSA card or sink)."""

    card_index: int
    card_id: str
    card_name: str
    driver: str
    is_usb_dac: bool = False
    hw_device: str = ""
    plughw_device: str = ""
    supported_rates: list[int] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=list)
    extra_info: str = ""

    def __post_init__(self) -> None:
        if not self.hw_device:
            self.hw_device = f"hw:{self.card_index},0"
        if not self.plughw_device:
            self.plughw_device = f"plughw:{self.card_index},0"


def parse_proc_asound_cards(cards_content: str) -> list[dict[str, Any]]:
    """Parse /proc/asound/cards text into structured card dictionaries."""
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


def probe_usb_dac_stream_info(card_index: int) -> tuple[list[int], list[str]]:
    """Probe /proc/asound/cardX/stream0 for supported sample rates and bit depths."""
    stream_path = Path(f"/proc/asound/card{card_index}/stream0")
    if not stream_path.exists():
        return list(STANDARD_RATES[:4]), ["S16_LE", "S24_LE", "S32_LE"]

    rates: set[int] = set()
    formats: set[str] = set()
    try:
        content = stream_path.read_text(encoding="utf-8", errors="replace")
        for line in content.splitlines():
            line_str = line.strip()
            if "Rates:" in line_str:
                parts = line_str.replace("Rates:", "").replace(",", " ").split()
                for p in parts:
                    try:
                        rates.add(int(p.strip()))
                    except ValueError:
                        pass
            if "Format:" in line_str:
                fmt = line_str.replace("Format:", "").strip()
                if fmt:
                    formats.add(fmt)
    except Exception as err:
        logger.debug("Error probing stream0 for card %d: %s", card_index, err)

    sorted_rates = sorted(rates) if rates else list(STANDARD_RATES[:4])
    sorted_formats = sorted(formats) if formats else ["S16_LE", "S24_LE", "S32_LE"]
    return sorted_rates, sorted_formats


def discover_audio_endpoints() -> list[AudioEndpointInfo]:
    """Scan the system for ALSA audio cards and classify them."""
    endpoints: list[AudioEndpointInfo] = []
    asound_cards = Path("/proc/asound/cards")
    if not asound_cards.exists():
        return endpoints

    try:
        content = asound_cards.read_text(encoding="utf-8", errors="replace")
        parsed = parse_proc_asound_cards(content)
        for c in parsed:
            c_idx = c["card_index"]
            driver = c.get("driver", "")
            name = c.get("card_name", "")
            extra = c.get("extra_info", "")

            # Identify if it is a USB DAC
            is_usb = (
                "usb" in driver.lower()
                or "usb" in name.lower()
                or "usb" in extra.lower()
                or any(
                    k in name.lower()
                    for k in (
                        "dac",
                        "letshuoer",
                        "fiio",
                        "schiit",
                        "topping",
                        "chord",
                        "audioquest",
                        "dragonfly",
                        "moondrop",
                        "hifiman",
                        "focusrite",
                    )
                )
            )

            rates, formats = probe_usb_dac_stream_info(c_idx) if is_usb else (list(STANDARD_RATES[:4]), ["S16_LE", "S24_LE"])
            endpoint = AudioEndpointInfo(
                card_index=c_idx,
                card_id=c.get("card_id", f"card{c_idx}"),
                card_name=name,
                driver=driver,
                is_usb_dac=is_usb,
                hw_device=f"hw:{c_idx},0",
                plughw_device=f"plughw:{c_idx},0",
                supported_rates=rates,
                supported_formats=formats,
                extra_info=extra,
            )
            endpoints.append(endpoint)
    except Exception as err:
        logger.warning("Error discovering audio endpoints: %s", err)

    return endpoints


def get_active_or_best_dac(endpoints: list[AudioEndpointInfo] | None = None) -> AudioEndpointInfo | None:
    """Return the best available USB DAC or external audiophile endpoint."""
    all_endpoints = endpoints if endpoints is not None else discover_audio_endpoints()
    dacs = [ep for ep in all_endpoints if ep.is_usb_dac]
    if dacs:
        # Prioritize known high-end DACs if multiple
        for dac in dacs:
            name = dac.card_name.lower()
            if any(k in name for k in ("letshuoer", "fiio", "topping", "schiit", "chord")):
                return dac
        return dacs[0]
    return None


def swap_playback_output(target_profile: str) -> str:
    """Dynamic output switching helper that transfers active playback to the specified profile.

    Ensures that if music is actively playing, playback continues immediately
    on the newly selected output.
    """
    from vibeplay.player import get_mpd_transport, get_playback_status, set_output_profile

    # 1. Check current playback state
    status_before = get_playback_status()
    was_playing = status_before.get("state") == "play"
    current_elapsed = status_before.get("elapsed", 0.0)

    # 2. Switch the active profile in the player / MPD
    active = set_output_profile(target_profile)

    # 3. If playback was active, ensure it keeps playing smoothly on the new output
    if was_playing:
        try:
            with get_mpd_transport() as transport:
                if transport.client:
                    st = transport.status()
                    if st.get("state") != "play":
                        transport.client.play()
                        if current_elapsed > 1.0:
                            try:
                                transport.client.seekcur(int(current_elapsed))
                            except Exception:
                                pass
        except Exception as err:
            logger.debug("Playback transfer warning during output switch: %s", err)

    return active
