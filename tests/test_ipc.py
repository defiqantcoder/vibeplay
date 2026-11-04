"""Unit and integration tests for vibe_dsp IPC socket and profile switching (Phase 5.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_dsp.ipc import (
    AVAILABLE_PROFILES,
    DSPClient,
    ProfileSwitchError,
    get_current_dsp_status,
    load_persistent_state,
    save_persistent_state,
    start_ipc_server,
    switch_audio_profile,
)
from vibe_dsp.models import AudioEndpoint, AuditReport, CardType


def test_available_profiles_structure() -> None:
    """Verify standard profiles: pure-bitperfect, spatial-headphones, receiver-passthrough."""
    profile_ids = [p["id"] for p in AVAILABLE_PROFILES]
    assert "pure-bitperfect" in profile_ids
    assert "spatial-headphones" in profile_ids
    assert "receiver-passthrough" in profile_ids


def test_persistent_state_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify loading and saving persistent DSP state file."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("vibe_dsp.ipc.DEFAULT_STATE_FILE", state_file)
    monkeypatch.setattr("vibe_dsp.ipc.DEFAULT_IPC_DIR", tmp_path)

    initial = load_persistent_state()
    assert "active_profile" in initial

    new_state = {
        "active_profile": "spatial-headphones",
        "spatial_mode": "3d_binaural",
        "spatial_active": True,
        "receiver_codecs": ["ac3", "truehd"],
        "active_peq_preset": "sennheiser_hd600",
    }
    save_persistent_state(new_state)

    loaded = load_persistent_state()
    assert loaded["active_profile"] == "spatial-headphones"
    assert loaded["active_peq_preset"] == "sennheiser_hd600"


def test_switch_audio_profile_invalid() -> None:
    """Verify unknown profile ID raises ProfileSwitchError."""
    with pytest.raises(ProfileSwitchError, match="Invalid profile"):
        switch_audio_profile("nonexistent-profile-xyz")


def test_switch_audio_profile_spatial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify switching to spatial-headphones activates 3D binaural virtualization."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr("vibe_dsp.ipc.DEFAULT_STATE_FILE", state_file)
    monkeypatch.setattr("vibe_dsp.ipc.DEFAULT_IPC_DIR", tmp_path)

    with patch("vibe_dsp.ipc.set_spatial_virtualization_mode", return_value=True) as mock_mode:
        res = switch_audio_profile("spatial-headphones")
        assert res["status"] == "ok"
        assert res["active_profile"] == "spatial-headphones"
        mock_mode.assert_called_with("3d_binaural")


def test_dsp_client_in_process_fallback(tmp_path: Path) -> None:
    """Verify DSPClient handles commands gracefully even when UNIX socket is offline."""
    nonexistent_socket = tmp_path / "offline.sock"
    client = DSPClient(socket_path=nonexistent_socket)

    profiles = client.list_profiles()
    assert len(profiles) >= 3

    status = client.get_status()
    assert "active_profile" in status
    assert "spatial" in status


@pytest.mark.anyio
async def test_ipc_server_and_client_unix_socket(tmp_path: Path) -> None:
    """Verify full end-to-end communication over UNIX domain socket."""
    sock_path = tmp_path / "test_ipc.sock"
    server = await start_ipc_server(socket_path=sock_path)

    client = DSPClient(socket_path=sock_path)
    try:
        status = client.get_status()
        assert "active_profile" in status

        profiles = client.list_profiles()
        assert any(p["id"] == "pure-bitperfect" for p in profiles)
    finally:
        server.close()
        await server.wait_closed()


@patch("vibe_dsp.ipc.scan_hardware")
@patch("vibe_dsp.ipc.get_active_peq_state")
@patch("vibe_dsp.ipc.get_spatial_virtualization_status")
@patch("vibe_dsp.ipc.load_persistent_state")
def test_get_current_dsp_status(mock_load, mock_spatial, mock_peq, mock_scan):
    """Verify get_current_dsp_status aggregates underlying DSP modules correctly."""
    mock_load.return_value = {"active_profile": "spatial-headphones", "spatial_mode": "3d_binaural"}
    mock_spatial.return_value = {"active": True, "sink_name": "spatial-sink"}
    mock_peq.return_value = {"active": True, "preset": "hd600"}

    mock_hw = AuditReport(
        endpoints=[
            AudioEndpoint(
                card_index=1, card_id="KA15", card_name="FIIO KA15", driver="USB-Audio", device_name="USB Audio", card_type=CardType.USB_DAC
            )
        ],
        active_dac=AudioEndpoint(
            card_index=1, card_id="KA15", card_name="FIIO KA15", driver="USB-Audio", device_name="USB Audio", card_type=CardType.USB_DAC
        ),
    )
    mock_scan.return_value = mock_hw

    status = get_current_dsp_status()

    assert status["active_profile"] == "spatial-headphones"
    assert status["spatial"]["active"] is True
    assert status["spatial"]["mode"] == "3d_binaural"
    assert status["peq"]["preset"] == "hd600"
    assert status["hardware"]["active_dac"] == "FIIO KA15"
    assert status["hardware"]["endpoint_count"] == 1


@patch("vibe_dsp.ipc.scan_hardware")
@patch("vibe_dsp.ipc.get_active_peq_state")
@patch("vibe_dsp.ipc.get_spatial_virtualization_status")
@patch("vibe_dsp.ipc.load_persistent_state")
def test_get_current_dsp_status_no_dac(mock_load, mock_spatial, mock_peq, mock_scan):
    """Verify get_current_dsp_status gracefully handles absence of a DAC."""
    mock_load.return_value = {}
    mock_spatial.return_value = {}
    mock_peq.return_value = {}

    mock_hw = AuditReport(endpoints=[], active_dac=None)
    mock_scan.return_value = mock_hw

    status = get_current_dsp_status()

    assert status["active_profile"] == "pure-bitperfect"
    assert status["hardware"]["active_dac"] is None
    assert status["hardware"]["endpoint_count"] == 0
