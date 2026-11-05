"""Regression coverage for output profiles and settings failure responses."""

import json
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from vibeplay import player
from vibeplay.desktop.settings import DesktopSettings
from vibeplay.routers import player as player_router
from vibeplay.routers import settings as settings_router


class CardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and "output-device-card" in attrs.get("class", ""):
            self.cards.append((attrs["class"].split(), json.loads(attrs["hx-vals"])["profile"]))


def render_cards(profiles, active):
    html = player_router.templates.get_template("components/output_switcher.html").render(
        playback={"active_profile": active, "output_profile": active, "output_profiles": profiles},
        popover_open=True,
    )
    parser = CardParser()
    parser.feed(html)
    return parser.cards, html


def test_switcher_renders_names_and_matches_active_profile():
    names = ["PipeWire Sound Server", "DAC \"Studio\" & Co's hw:1,0"]
    profiles = [{"id": str(i), "name": name, "type": "mpd"} for i, name in enumerate(names)]
    cards, html = render_cards(profiles, "  dac \"studio\" & co's HW:1,0  ")
    assert [name for _, name in cards] == names
    assert ["active" in classes for classes, _ in cards] == [False, True]
    assert "Direct ALSA • 32-bit" in html
    assert "{'id':" not in html


def test_switcher_keeps_alias_and_empty_fallbacks():
    cards, _ = render_cards([{"id": "x", "name": "Pure Bit-Perfect (Direct ALSA)", "type": "alsa"}], "pure-bitperfect")
    assert "active" in cards[0][0]
    cards, _ = render_cards([], "")
    assert cards[0][1] == "Pure Bit-Perfect (Direct ALSA)"


def test_mpd_profiles_skip_duplicate_ids_and_names(monkeypatch):
    monkeypatch.setattr(player, "parse_asound_cards_dynamic", lambda: [])
    monkeypatch.setattr("vibe_dsp.hardware.scan_hardware", lambda: SimpleNamespace(endpoints=[], active_dac=None, fallback_endpoint=None))
    transport = MagicMock()
    transport.client.outputs.return_value = [
        {"outputid": 1, "outputname": "Desk"},
        {"outputid": "1", "outputname": "Different name"},
        {"outputid": 2, "outputname": "DESK"},
        {"outputid": 3, "outputname": "pipewire sound server"},
        {"outputid": "pure-bitperfect", "outputname": "Another duplicate ID"},
        {"outputid": 4, "outputname": "FiiO disconnected"},
        {"outputid": 5, "outputname": "Other output"},
    ]
    context = MagicMock()
    context.__enter__.return_value = transport
    monkeypatch.setattr(player, "get_mpd_transport", lambda cfg: context)
    profiles = player.get_output_profiles()
    assert [(p["id"], p["name"]) for p in profiles if p["type"] == "mpd"] == [("1", "Desk"), ("5", "Other output")]


@pytest.fixture
def router_client():
    app = FastAPI()
    app.include_router(player_router.router)
    app.include_router(settings_router.router)
    return TestClient(app)


def test_output_failure_and_expected_http_exception(router_client, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise RuntimeError("routing failed")

    monkeypatch.setattr(player_router, "set_output_profile", fail)
    response = router_client.post("/api/player/output", data={"profile": "Desk"})
    assert response.status_code == 500
    assert response.json() == {"status": "error", "message": "Failed to set profile"}
    assert "routing failed" in caplog.text

    def reject(*args, **kwargs):
        raise HTTPException(status_code=409, detail="conflict")

    monkeypatch.setattr(player_router, "set_output_profile", reject)
    assert router_client.post("/api/player/output", data={"profile": "Desk"}).status_code == 409


def test_output_dsp_dispatch_failure_remains_nonfatal(router_client, monkeypatch):
    monkeypatch.setattr(player_router, "set_output_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(player_router, "get_playback_status", lambda *args: {})
    monkeypatch.setattr(player_router, "get_output_profiles", lambda *args: [])

    def fail(*args, **kwargs):
        raise OSError("DSP unavailable")

    monkeypatch.setattr("vibe_dsp.ipc.DSPClient.set_profile", fail)
    response = router_client.post("/api/player/output?format=json", data={"profile": "Desk"})
    assert response.status_code == 200
    assert response.json()["active_profile"] == "Desk"


def test_output_profile_round_trips_in_json_and_escaped_html(router_client, monkeypatch):
    profile = 'DAC "Studio" & <script>alert(1)</script>\'s'
    committed = []
    monkeypatch.setattr(player_router, "set_output_profile", lambda name, settings: committed.append(name))
    monkeypatch.setattr(player_router, "get_playback_status", lambda *args: {})
    monkeypatch.setattr(player_router, "get_output_profiles", lambda *args: [
        {"id": "first", "name": "Other", "type": "mpd"},
        {"id": "target", "name": profile, "type": "mpd"},
    ])
    monkeypatch.setattr("vibe_dsp.ipc.DSPClient.set_profile", lambda *args: None)

    response = router_client.post("/api/player/output?format=json", data={"profile": profile})
    assert response.status_code == 200
    assert response.json()["active_profile"] == profile
    assert response.json()["playback"]["active_profile"] == profile
    assert response.json()["playback"]["output_profile"] == profile

    response = router_client.post("/api/player/output", data={"profile": profile})
    assert response.status_code == 200
    parser = CardParser()
    parser.feed(response.text)
    assert [("active" in classes, name) for classes, name in parser.cards] == [(False, "Other"), (True, profile)]
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "&amp;lt;script" not in response.text
    assert committed == [profile, profile]


def test_gemini_save_failure_has_no_key(router_client, monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(settings_router, "update_desktop_settings", fail)
    response = router_client.post("/api/settings/api-key", json={"gemini_api_key": "secret"})
    assert response.status_code == 500
    assert response.json() == {"status": "error", "message": "Operation failed"}
    assert len([r for r in caplog.records if r.name == settings_router.__name__]) == 1
    assert "disk full" in caplog.text


@pytest.mark.parametrize("error", [OSError("disk full"), RuntimeError("unexpected failure")])
def test_settings_save_failure_has_no_settings(router_client, monkeypatch, caplog, error):
    monkeypatch.setattr(settings_router, "safe_load_settings", lambda: DesktopSettings())

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(settings_router, "save_desktop_settings", fail)
    response = router_client.post("/api/settings", json={"theme_id": "wine"})
    assert response.status_code == 500
    assert response.json() == {"status": "error", "message": "Operation failed"}
    assert str(error) in caplog.text


def test_settings_validation_and_success_responses(router_client, monkeypatch):
    monkeypatch.setattr(settings_router, "safe_load_settings", lambda: DesktopSettings())
    saved = []
    monkeypatch.setattr(settings_router, "save_desktop_settings", saved.append)
    assert router_client.post("/api/settings", json={"alsa_buffer_frames": 999}).status_code == 422
    response = router_client.post("/api/settings", json={"theme_id": "wine"})
    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert saved[0].theme_id == "wine"
