"""Unit and integration tests for vibe_dsp IPC socket and profile switching (Phase 5.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from vibe_dsp.ipc import (
    AVAILABLE_PROFILES,
    DSPClient,
    ProfileSwitchError,
    load_persistent_state,
    save_persistent_state,
    start_ipc_server,
    switch_audio_profile,
)


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


@pytest.mark.parametrize("has_dac", [True, False])
def test_switch_audio_profile_bitperfect_writes_outputs(tmp_path, monkeypatch, mocker, has_dac):
    from vibe_dsp.models import AudioEndpoint, AuditReport, CardType

    dac = AudioEndpoint(card_index=1, card_id="dac", card_name="USB DAC", driver="usb", device_name="DAC", card_type=CardType.USB_DAC)
    speaker = AudioEndpoint(card_index=0, card_id="speaker", card_name="Speaker", driver="hda", device_name="Analog", card_type=CardType.SPEAKER_ANALOG)
    monkeypatch.setattr("vibe_dsp.ipc.DEFAULT_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("vibe_dsp.ipc.DEFAULT_IPC_DIR", tmp_path)
    mocker.patch("vibe_dsp.ipc.scan_hardware", return_value=AuditReport(active_dac=dac if has_dac else None, fallback_endpoint=speaker))
    write = mocker.patch("vibe_dsp.ipc.write_mpd_audio_outputs_config")
    mocker.patch("vibe_dsp.ipc.apply_wpctl_sink_rate_override")
    mocker.patch("vibe_dsp.ipc.set_spatial_virtualization_mode")
    assert switch_audio_profile("pure-bitperfect")["status"] == "ok"
    config = write.call_args.args[0]
    if has_dac:
        assert 'device          "hw:1,0"' in config
    assert 'device          "hw:0,0"' in config
    assert 'auto_resample   "no"' in config
    assert load_persistent_state()["active_profile"] == "pure-bitperfect"


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
