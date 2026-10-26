"""Inter-Process Communication (IPC) socket server and client for dynamic DSP profile switching."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from vibe_dsp.alsa_reservation import (
    generate_mpd_audio_outputs,
    write_mpd_audio_outputs_config,
)
from vibe_dsp.hardware import scan_hardware
from vibe_dsp.passthrough import (
    configure_sink_passthrough,
    discover_receiver_endpoints,
)
from vibe_dsp.peq import apply_peq_preset, get_active_peq_state
from vibe_dsp.pipewire import apply_wpctl_sink_rate_override
from vibe_dsp.spatial import (
    get_spatial_virtualization_status,
    set_spatial_virtualization_mode,
)

logger = logging.getLogger(__name__)

DEFAULT_IPC_DIR = Path("~/.config/vibe-dsp").expanduser()
DEFAULT_IPC_SOCKET_PATH = DEFAULT_IPC_DIR / "ipc.sock"
DEFAULT_STATE_FILE = DEFAULT_IPC_DIR / "state.json"

AVAILABLE_PROFILES: list[dict[str, Any]] = [
    {
        "id": "pure-bitperfect",
        "name": "Pure Bit-Perfect",
        "description": "Direct ALSA hardware exclusive (strictly bypasses desktop mixers and software resampling)",
        "target": "alsa_hw",
    },
    {
        "id": "spatial-headphones",
        "name": "7.1.4 Spatial Headphones",
        "description": "PipeWire 7.1.4 SOFA Binaural Virtualization + Transducer PEQ with inter-sample anti-clipping",
        "target": "pipewire_spatial",
    },
    {
        "id": "receiver-passthrough",
        "name": "AV Receiver Passthrough",
        "description": "HDMI/SPDIF raw bitstream direct (AC3, EAC3, TrueHD, DTS-HD hardware decoding)",
        "target": "hdmi_bitstream",
    },
]


class ProfileSwitchError(Exception):
    """Raised when profile transition fails."""

    pass


def load_persistent_state() -> dict[str, Any]:
    """Load persistent DSP state from disk."""
    if DEFAULT_STATE_FILE.exists():
        try:
            return json.loads(DEFAULT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "active_profile": "pure-bitperfect",
        "spatial_mode": "stereo_direct",
        "spatial_active": False,
        "receiver_codecs": ["ac3", "eac3", "dts", "truehd", "dts-hd"],
        "active_peq_preset": None,
    }


def save_persistent_state(state: dict[str, Any]) -> None:
    """Save persistent DSP state to disk with restricted permissions (0600)."""
    try:
        DEFAULT_IPC_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        DEFAULT_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        try:
            DEFAULT_STATE_FILE.chmod(0o600)
        except OSError:
            pass
    except Exception as err:
        logger.warning("Failed to save DSP persistent state: %s", err)


def switch_audio_profile(profile_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Switch audio profile on the fly across ALSA, PipeWire, and receiver outputs.

    Supported profiles:
    1. 'pure-bitperfect' (Direct ALSA hardware exclusive)
    2. 'spatial-headphones' (PipeWire 7.1.4 SOFA Convolver + Transducer PEQ)
    3. 'receiver-passthrough' (HDMI Bitstream Direct)

    Args:
        profile_id: Target profile identifier.
        options: Optional parameters (e.g. peq_model, hdmi_sink, codecs).

    Returns:
        dict[str, Any]: Resulting profile state dictionary.
    """
    opts = options or {}
    clean_id = profile_id.lower().strip()
    valid_ids = {p["id"] for p in AVAILABLE_PROFILES}

    if clean_id not in valid_ids:
        raise ProfileSwitchError(
            f"Invalid profile '{profile_id}'. Available profiles: {', '.join(sorted(valid_ids))}"
        )

    state = load_persistent_state()

    if clean_id == "pure-bitperfect":
        # 1. Pure Bit-Perfect (Direct ALSA Hardware Exclusive)
        report = scan_hardware()
        target_dac = report.active_dac or report.fallback_endpoint
        if target_dac:
            mpd_cfg = generate_mpd_audio_outputs(
                endpoints=report.endpoints,
                primary_device=target_dac.hw_device,
                enable_bitperfect=True,
            )
            write_mpd_audio_outputs_config(mpd_cfg)
        apply_wpctl_sink_rate_override()
        # Set spatial virtualization to bypass
        set_spatial_virtualization_mode("stereo_direct")
        state["active_profile"] = "pure-bitperfect"
        state["spatial_active"] = False
        state["spatial_mode"] = "stereo_direct"

    elif clean_id == "spatial-headphones":
        # 2. 7.1.4 Spatial Headphones (SOFA Convolver + Transducer PEQ)
        # Enable 3D binaural virtualization on Spatial-7.1.4-Sink
        set_spatial_virtualization_mode("3d_binaural")
        peq_preset = opts.get("peq_preset") or state.get("active_peq_preset")
        if peq_preset:
            try:
                apply_peq_preset(peq_preset)
                state["active_peq_preset"] = peq_preset
            except Exception as err:
                logger.warning("Could not apply PEQ preset %s: %s", peq_preset, err)

        state["active_profile"] = "spatial-headphones"
        state["spatial_active"] = True
        state["spatial_mode"] = "3d_binaural"

    elif clean_id == "receiver-passthrough":
        # 3. AV Receiver Passthrough (HDMI Bitstream Direct)
        # Query receiver endpoints
        receivers = discover_receiver_endpoints()
        codecs = opts.get("codecs") or state.get("receiver_codecs") or ["ac3", "eac3", "dts", "truehd", "dts-hd"]
        if receivers:
            target_sink = opts.get("sink") or receivers[0].sink_id
            configure_sink_passthrough(target_sink, selected_codecs=codecs, set_as_default=True)
        set_spatial_virtualization_mode("stereo_direct")
        state["active_profile"] = "receiver-passthrough"
        state["spatial_active"] = False
        state["spatial_mode"] = "stereo_direct"
        state["receiver_codecs"] = codecs

    save_persistent_state(state)
    return {
        "status": "ok",
        "active_profile": state["active_profile"],
        "message": f"Successfully activated audio profile '{clean_id}'",
        "state": state,
    }


def get_current_dsp_status() -> dict[str, Any]:
    """Compile comprehensive DSP status including active profile, spatial sink, and PEQ state."""
    state = load_persistent_state()
    spatial_status = get_spatial_virtualization_status()
    peq_status = get_active_peq_state()
    hw_report = scan_hardware()

    return {
        "active_profile": state.get("active_profile", "pure-bitperfect"),
        "available_profiles": AVAILABLE_PROFILES,
        "spatial": {
            **spatial_status,
            "mode": state.get("spatial_mode", "stereo_direct"),
        },
        "peq": peq_status,
        "hardware": {
            "active_dac": hw_report.active_dac.card_name if hw_report.active_dac else None,
            "endpoint_count": len(hw_report.endpoints),
        },
    }


async def handle_ipc_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle incoming JSON-RPC client connection on the UNIX domain socket."""
    try:
        raw_data = await reader.read(65536)
        if not raw_data:
            return

        message = json.loads(raw_data.decode("utf-8"))
        action = message.get("action", "")

        response: dict[str, Any]

        if action == "get_status":
            response = {"status": "ok", "data": get_current_dsp_status()}

        elif action == "get_profile":
            state = load_persistent_state()
            response = {"status": "ok", "profile": state.get("active_profile", "pure-bitperfect")}

        elif action == "set_profile":
            profile_id = message.get("profile", "")
            options = message.get("options", {})
            try:
                res = switch_audio_profile(profile_id, options)
                response = res
            except Exception as err:
                response = {"status": "error", "message": str(err)}

        elif action == "list_profiles":
            response = {"status": "ok", "profiles": AVAILABLE_PROFILES}

        elif action == "toggle_spatial":
            mode = message.get("mode", "3d_binaural")
            success = set_spatial_virtualization_mode(mode)
            state = load_persistent_state()
            state["spatial_mode"] = mode
            state["spatial_active"] = (mode == "3d_binaural")
            save_persistent_state(state)
            response = {"status": "ok" if success else "warning", "mode": mode, "applied": success}

        else:
            response = {"status": "error", "message": f"Unknown action '{action}'"}

        writer.write(json.dumps(response).encode("utf-8") + b"\n")
        await writer.drain()
    except Exception as err:
        logger.warning("Error processing IPC client request: %s", err)
        err_response = {"status": "error", "message": str(err)}
        writer.write(json.dumps(err_response).encode("utf-8") + b"\n")
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def start_ipc_server(socket_path: Path | None = None) -> asyncio.Server:
    """Start the asynchronous UNIX domain socket server."""
    sock_path = socket_path or DEFAULT_IPC_SOCKET_PATH
    sock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    if sock_path.exists():
        try:
            sock_path.unlink()
        except OSError:
            pass

    server = await asyncio.start_unix_server(handle_ipc_client, path=str(sock_path))
    try:
        sock_path.chmod(0o600)
    except OSError:
        pass
    logger.info("DSP IPC server listening on UNIX socket: %s", sock_path)
    return server


class DSPClient:
    """Client for communicating with vibe-dsp IPC socket or local fallback."""

    def __init__(self, socket_path: Path | None = None) -> None:
        self.socket_path = socket_path or DEFAULT_IPC_SOCKET_PATH

    def _call_socket_sync(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        """Send request payload to UNIX socket synchronously with direct in-process fallback."""
        if not self.socket_path.exists():
            return self._fallback_direct_call(request_payload)

        try:
            import socket

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(str(self.socket_path))
                s.sendall(json.dumps(request_payload).encode("utf-8"))
                response_data = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk
                return json.loads(response_data.decode("utf-8"))
        except Exception as err:
            logger.debug("UNIX socket connection failed (%s); using in-process dispatch", err)
            return self._fallback_direct_call(request_payload)

    def _fallback_direct_call(self, request: dict[str, Any]) -> dict[str, Any]:
        """Direct in-process fallback when IPC socket daemon is not running."""
        action = request.get("action", "")
        if action == "get_status":
            return {"status": "ok", "data": get_current_dsp_status()}
        elif action == "get_profile":
            state = load_persistent_state()
            return {"status": "ok", "profile": state.get("active_profile", "pure-bitperfect")}
        elif action == "set_profile":
            return switch_audio_profile(request.get("profile", ""), request.get("options", {}))
        elif action == "list_profiles":
            return {"status": "ok", "profiles": AVAILABLE_PROFILES}
        elif action == "toggle_spatial":
            mode = request.get("mode", "3d_binaural")
            success = set_spatial_virtualization_mode(mode)
            return {"status": "ok" if success else "warning", "mode": mode, "applied": success}
        return {"status": "error", "message": f"Unsupported action: {action}"}

    def get_status(self) -> dict[str, Any]:
        """Fetch complete DSP status."""
        res = self._call_socket_sync({"action": "get_status"})
        return res.get("data", {})

    def get_profile(self) -> str:
        """Fetch active profile id."""
        res = self._call_socket_sync({"action": "get_profile"})
        return res.get("profile", "pure-bitperfect")

    def set_profile(self, profile_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Set audio profile."""
        return self._call_socket_sync({
            "action": "set_profile",
            "profile": profile_id,
            "options": options or {},
        })

    def list_profiles(self) -> list[dict[str, Any]]:
        """List available audio profiles."""
        res = self._call_socket_sync({"action": "list_profiles"})
        return res.get("profiles", AVAILABLE_PROFILES)

    def toggle_spatial(self, mode: str) -> dict[str, Any]:
        """Toggle spatial virtualization mode."""
        return self._call_socket_sync({"action": "toggle_spatial", "mode": mode})
