"""Comprehensive unit and integration tests for vibe-dsp (Phase 5.1).

Tests dynamic ALSA procfs parsing, USB Audio Class capability probing,
PipeWire bit-perfect drop-in generation, MPD direct ALSA reservation,
atomic backup and rollback automation, and Typer CLI workflows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from vibe_dsp.alsa_reservation import (
    check_alsa_device_status,
    generate_mpd_audio_outputs,
    write_mpd_audio_outputs_config,
)
from vibe_dsp.backup import (
    create_backup,
    execute_rollback,
    find_latest_backup,
)
from vibe_dsp.cli import app
from vibe_dsp.hardware import (
    STANDARD_UNLOCKED_RATES,
    parse_proc_asound_cards,
    parse_proc_asound_pcm,
    parse_usb_stream_capabilities,
    scan_hardware,
)
from vibe_dsp.models import AudioEndpoint, AuditReport, CardType
from vibe_dsp.pipewire import (
    generate_pipewire_dropin_config,
    reload_pipewire_daemons,
    write_pipewire_dropin,
)

runner = CliRunner()

MOCK_CARDS_MULTI = """\
 0 [sofhdadsp      ]: sof-hda-dsp - sof-hda-dsp
                      HP-HPEnvyx3602_in_1Laptop14_es0xxx-Type1ProductConfigId-8BF7
 1 [KA15           ]: USB-Audio - FIIO KA15
                      FIIO FIIO KA15 at usb-0000:00:14.0-3, high speed
"""

MOCK_CARDS_NO_DAC = """\
 0 [sofhdadsp      ]: sof-hda-dsp - sof-hda-dsp
                      HP-HPEnvyx3602_in_1Laptop14_es0xxx-Type1ProductConfigId-8BF7
"""

MOCK_PCM_CONTENT = """\
00-00: HDA Analog (*) :  : playback 1 : capture 1
00-03: HDMI1 (*) : HDMI 1 : playback 1
00-04: HDMI2 (*) : HDMI 2 : playback 1
00-05: HDMI3 (*) : HDMI 3 : playback 1
01-00: USB Audio : USB Audio : playback 1 : capture 1
"""

MOCK_STREAM_KA15 = """\
FIIO FIIO KA15 at usb-0000:00:14.0-3, high speed : USB Audio

Playback:
  Status: Stop
  Interface 1
    Altset 1
    Format: S16_LE
    Channels: 2
    Endpoint: 0x01 (1 OUT) (ASYNC)
    Rates: 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000, 705600, 768000
    Data packet interval: 125 us
    Bits: 16
  Interface 1
    Altset 2
    Format: S32_LE
    Channels: 2
    Endpoint: 0x01 (1 OUT) (ASYNC)
    Rates: 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000, 705600, 768000
    Data packet interval: 125 us
    Bits: 32
  Interface 1
    Altset 3
    Format: DSD_U32_BE
    Channels: 2
    Endpoint: 0x01 (1 OUT) (ASYNC)
    Rates: 44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000, 705600, 768000
    Data packet interval: 125 us
    Bits: 32
"""


# -----------------------------------------------------------------------------
# Hardware Procfs Parsing Tests
# -----------------------------------------------------------------------------

def test_parse_proc_asound_cards():
    """Verify parsing of /proc/asound/cards with hyphenated driver names."""
    cards = parse_proc_asound_cards(MOCK_CARDS_MULTI)
    assert len(cards) == 2

    assert cards[0]["card_index"] == 0
    assert cards[0]["card_id"] == "sofhdadsp"
    assert cards[0]["driver"] == "sof-hda-dsp"
    assert cards[0]["card_name"] == "sof-hda-dsp"
    assert "HPEnvy" in cards[0]["extra_info"]

    assert cards[1]["card_index"] == 1
    assert cards[1]["card_id"] == "KA15"
    assert cards[1]["driver"] == "USB-Audio"
    assert cards[1]["card_name"] == "FIIO KA15"
    assert "high speed" in cards[1]["extra_info"]


def test_parse_proc_asound_pcm():
    """Verify extracting playback PCM device numbers."""
    devices = parse_proc_asound_pcm(MOCK_PCM_CONTENT)
    assert len(devices) == 5

    assert devices[0] == {"card_index": 0, "device_index": 0, "device_name": "HDA Analog (*)"}
    assert devices[1] == {"card_index": 0, "device_index": 3, "device_name": "HDMI1 (*)"}
    assert devices[4] == {"card_index": 1, "device_index": 0, "device_name": "USB Audio"}


def test_parse_usb_stream_capabilities():
    """Verify parsing USB Audio Class rates, formats, and bit depths."""
    caps = parse_usb_stream_capabilities(MOCK_STREAM_KA15)
    assert 44100 in caps["rates"]
    assert 384000 in caps["rates"]
    assert 768000 in caps["rates"]
    assert "DSD_U32_BE" in caps["formats"]
    assert "S32_LE" in caps["formats"]
    assert 16 in caps["bit_depths"]
    assert 32 in caps["bit_depths"]
    assert caps["channels"] == 2


def test_scan_hardware_prioritizes_connected_dac(tmp_path: Path):
    """Verify that a connected USB DAC is prioritized as active_dac."""
    proc_root = tmp_path / "asound"
    proc_root.mkdir()
    (proc_root / "cards").write_text(MOCK_CARDS_MULTI)
    (proc_root / "pcm").write_text(MOCK_PCM_CONTENT)

    card1_dir = proc_root / "card1"
    card1_dir.mkdir()
    (card1_dir / "usbid").write_text("2972:0104\n")
    (card1_dir / "usbbus").write_text("003/014\n")
    (card1_dir / "stream0").write_text(MOCK_STREAM_KA15)

    report = scan_hardware(procfs_root=proc_root)
    assert report.active_dac is not None
    assert report.active_dac.card_index == 1
    assert report.active_dac.card_name == "FIIO KA15"
    assert report.active_dac.card_type == CardType.USB_DAC
    assert report.active_dac.hw_device == "hw:1,0"
    assert report.active_dac.plughw_device == "plughw:1,0"
    assert report.active_dac.max_rate == 768000

    # Fallback should be internal analog speaker
    assert report.fallback_endpoint is not None
    assert report.fallback_endpoint.card_index == 0
    assert report.fallback_endpoint.device_index == 0
    assert report.fallback_endpoint.card_type == CardType.SPEAKER_ANALOG


def test_scan_hardware_fallback_when_no_dac(tmp_path: Path):
    """Verify that when no USB DAC is connected, active_dac is None and fallback is selected."""
    proc_root = tmp_path / "asound"
    proc_root.mkdir()
    (proc_root / "cards").write_text(MOCK_CARDS_NO_DAC)
    (proc_root / "pcm").write_text("00-00: HDA Analog (*) :  : playback 1\n00-03: HDMI1 : : playback 1\n")

    report = scan_hardware(procfs_root=proc_root)
    assert report.active_dac is None
    assert report.fallback_endpoint is not None
    assert report.fallback_endpoint.hw_device == "hw:0,0"


def test_scan_hardware_missing_procfs(tmp_path: Path):
    """Verify graceful handling when procfs directory does not exist."""
    non_existent = tmp_path / "does_not_exist"
    report = scan_hardware(procfs_root=non_existent)
    assert report.endpoints == []
    assert report.active_dac is None


# -----------------------------------------------------------------------------
# PipeWire Drop-in Configuration Tests
# -----------------------------------------------------------------------------

def test_generate_pipewire_dropin_config():
    """Verify generation of 99-bitperfect.conf with unlocked rates and resample bypass."""
    cfg = generate_pipewire_dropin_config()
    for rate in STANDARD_UNLOCKED_RATES:
        assert str(rate) in cfg

    assert "resample.disable = true" in cfg
    assert 'media.class = "Stream/Output/Audio"' in cfg
    assert 'node.name = "~alsa_output.usb-.*"' in cfg


def test_write_pipewire_dropin(tmp_path: Path):
    """Verify writing the dropin configuration to specified directory."""
    conf_dir = tmp_path / "pipewire.conf.d"
    target_file = write_pipewire_dropin(conf_dir=conf_dir)
    assert target_file.exists()
    assert target_file.name == "99-bitperfect.conf"
    content = target_file.read_text()
    assert "default.clock.rates" in content


# -----------------------------------------------------------------------------
# ALSA Device Reservation & MPD Configuration Tests
# -----------------------------------------------------------------------------

def test_generate_mpd_audio_outputs():
    """Verify MPD output block with hw:, plughw:, speakers, and pipewire fallback."""
    dac_ep = AudioEndpoint(
        card_index=1,
        device_index=0,
        card_id="KA15",
        card_name="FIIO KA15",
        driver="USB-Audio",
        device_name="USB Audio",
        card_type=CardType.USB_DAC,
        rates=[44100, 96000, 384000],
        formats=["S32_LE", "DSD_U32_BE"],
        bit_depths=[16, 24, 32],
    )
    speaker_ep = AudioEndpoint(
        card_index=0,
        device_index=0,
        card_id="sofhdadsp",
        card_name="sof-hda-dsp",
        driver="sof-hda-dsp",
        device_name="HDA Analog",
        card_type=CardType.SPEAKER_ANALOG,
        rates=[44100, 48000],
    )

    mpd_cfg = generate_mpd_audio_outputs(
        primary_endpoint=dac_ep,
        fallback_endpoint=speaker_ep,
    )

    # 1. Direct hardware
    assert 'device          "hw:1,0"' in mpd_cfg
    assert 'auto_resample   "no"' in mpd_cfg
    assert 'auto_channels   "no"' in mpd_cfg
    assert 'auto_format     "no"' in mpd_cfg
    assert 'dop             "yes"' in mpd_cfg
    assert 'mixer_type      "none"' in mpd_cfg

    # 2. Transparent fallback plug
    assert 'device          "plughw:1,0"' in mpd_cfg

    # 3. Speakers fallback
    assert 'device          "hw:0,0"' in mpd_cfg
    assert 'device          "plughw:0,0"' in mpd_cfg

    # 4. PipeWire transport fallback
    assert 'type            "pipewire"' in mpd_cfg


def test_write_mpd_audio_outputs_config(tmp_path: Path):
    """Verify writing the MPD configuration snippet to disk."""
    out_file = tmp_path / "mpd" / "bitperfect.conf"
    res = write_mpd_audio_outputs_config("audio_output { test }", output_path=out_file)
    assert res.exists()
    assert res.read_text() == "audio_output { test }"


# -----------------------------------------------------------------------------
# Backup & Rollback Tests
# -----------------------------------------------------------------------------

def test_backup_and_rollback_workflow(tmp_path: Path):
    """Verify that create_backup correctly snapshots files and rollback.sh reverts them."""
    backup_root = tmp_path / "backups"
    conf_dir = tmp_path / "config"
    conf_dir.mkdir()

    # Pre-existing file
    existing_file = conf_dir / "existing.conf"
    existing_file.write_text("original content")

    # Future file (does not exist yet)
    new_file = conf_dir / "new.conf"

    # Create backup before modification
    backup_dir, rollback_script = create_backup(
        targets=[existing_file, new_file],
        backup_root=backup_root,
    )

    assert backup_dir.exists()
    assert rollback_script.exists()
    assert (backup_dir / "existing.conf").read_text() == "original content"
    assert (backup_dir / "manifest.json").exists()

    manifest = json.loads((backup_dir / "manifest.json").read_text())
    assert len(manifest["items"]) == 2
    assert manifest["items"][0]["action"] == "restore"
    assert manifest["items"][1]["action"] == "delete"

    # Simulate modifying existing file and creating new file
    existing_file.write_text("modified content")
    new_file.write_text("new content")

    assert existing_file.read_text() == "modified content"
    assert new_file.exists()

    # Execute rollback
    success, output = execute_rollback(rollback_script)
    assert success is True

    # Verify rollback restored original state
    assert existing_file.read_text() == "original content"
    assert not new_file.exists()


def test_find_latest_backup(tmp_path: Path):
    """Verify selecting the most recent timestamped backup directory."""
    root = tmp_path / "backups"
    (root / "20260101_100000").mkdir(parents=True)
    (root / "20260101_100000" / "rollback.sh").write_text("#!/bin/bash\n")
    (root / "20260102_120000").mkdir(parents=True)
    (root / "20260102_120000" / "rollback.sh").write_text("#!/bin/bash\n")

    latest = find_latest_backup(backup_root=root)
    assert latest is not None
    assert "20260102_120000" in str(latest)


# -----------------------------------------------------------------------------
# CLI Integration Tests
# -----------------------------------------------------------------------------

def test_cli_hardware_audit(tmp_path: Path):
    """Test 'vibe-dsp hardware audit' command with mock procfs."""
    proc_root = tmp_path / "asound"
    proc_root.mkdir()
    (proc_root / "cards").write_text(MOCK_CARDS_MULTI)
    (proc_root / "pcm").write_text(MOCK_PCM_CONTENT)

    card1_dir = proc_root / "card1"
    card1_dir.mkdir()
    (card1_dir / "usbid").write_text("2972:0104\n")
    (card1_dir / "stream0").write_text(MOCK_STREAM_KA15)

    result = runner.invoke(app, ["hardware", "audit", "--procfs", str(proc_root)])
    assert result.exit_code == 0
    assert "vibe-dsp Audio Hardware Audit & Capability Scan" in result.output
    assert "FIIO KA15" in result.output
    assert "768.0" in result.output


def test_cli_route_bitperfect_dry_run(tmp_path: Path):
    """Test 'vibe-dsp route bitperfect --dry-run' command."""
    proc_root = tmp_path / "asound"
    proc_root.mkdir()
    (proc_root / "cards").write_text(MOCK_CARDS_MULTI)
    (proc_root / "pcm").write_text(MOCK_PCM_CONTENT)

    result = runner.invoke(
        app,
        ["route", "bitperfect", "--dry-run", "--procfs", str(proc_root)],
    )
    assert result.exit_code == 0
    assert "[DRY RUN MODE]" in result.output
    assert "resample.disable = true" in result.output
    assert 'device          "hw:1,0"' in result.output


def test_cli_route_bitperfect_apply_and_rollback(tmp_path: Path):
    """Test applying bit-perfect routing and subsequent rollback via CLI."""
    proc_root = tmp_path / "asound"
    proc_root.mkdir()
    (proc_root / "cards").write_text(MOCK_CARDS_MULTI)
    (proc_root / "pcm").write_text(MOCK_PCM_CONTENT)

    pw_conf = tmp_path / "pipewire" / "99-bitperfect.conf"
    mpd_conf = tmp_path / "mpd" / "bitperfect.conf"

    # Run with --no-reload to avoid systemctl in test environment
    result = runner.invoke(
        app,
        [
            "route",
            "bitperfect",
            "--no-reload",
            "--output-pipewire",
            str(pw_conf),
            "--output-mpd",
            str(mpd_conf),
            "--procfs",
            str(proc_root),
        ],
    )
    assert result.exit_code == 0
    assert pw_conf.exists()
    assert mpd_conf.exists()
    assert "Bit-perfect routing engaged" in result.output

    # Verify PipeWire conf has unlocked clock rates
    pw_text = pw_conf.read_text()
    assert "384000" in pw_text
    assert "resample.disable = true" in pw_text

    # Verify MPD conf has direct hw: and plug fallback
    mpd_text = mpd_conf.read_text()
    assert 'device          "hw:1,0"' in mpd_text
    assert 'device          "plughw:1,0"' in mpd_text

    # Test rollback CLI
    # Mock find_latest_backup or backup root
    result_rb = runner.invoke(app, ["rollback"])
    # If a backup exists, rollback succeeds
    assert result_rb.exit_code == 0
