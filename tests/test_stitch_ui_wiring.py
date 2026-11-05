"""Verification tests for Stitch UI Overhaul and Interactive Wiring."""

from __future__ import annotations

import re
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from vibeplay.config import Settings
from vibeplay.db import init_db
from vibeplay.web import create_app


@pytest.fixture
def wiring_env(tmp_path: Path):
    db_file = tmp_path / "test_wiring.db"
    settings_file = tmp_path / "desktop_settings.json"
    init_db(db_file)
    cfg = Settings(db_path=db_file, desktop_settings_path=settings_file)
    app = create_app(db_path=db_file, settings=cfg)
    client = TestClient(app)
    return db_file, client


@pytest.fixture
def client(wiring_env):
    return wiring_env[1]


def test_top_navigation_tabs_and_view_separation(client: TestClient):
    """Verify distinct screen separation tabs exist and match app.js showTab contract."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Navigation buttons
    assert 'id="nav-btn-lounge"' in html
    assert 'id="nav-btn-crate"' in html
    assert 'id="nav-btn-library"' in html
    assert 'id="nav-btn-builder"' in html
    assert 'id="nav-btn-dsp"' in html
    assert 'id="nav-btn-bigscreen"' in html

    # 2. Distinct Screen Tab Sections
    assert 'id="tab-library"' in html
    assert 'id="tab-builder"' in html
    assert 'id="tab-crate"' in html

    # 3. Default Visibility: Library visible by default, others isolated/hidden
    assert '<section id="tab-library" style="display: block;">' in html
    assert '<section id="tab-crate" style="display: none;">' in html
    assert '<section id="tab-builder" style="display: none;">' in html

    # 4. Workspace inspector drawer is hidden by default
    assert 'id="workspace-inspector-drawer"' in html
    assert 'style="display: none;"' in html


def test_soundbar_10_band_parametric_eq(client: TestClient):
    """Verify 10-Band Parametric Equalizer matches Stitch specification."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # Soundbar header & badges
    assert "The Soundbar" in html
    assert "(EQ Studio)" in html
    assert "DSP v2.4" in html
    assert "Bit-Perfect mode" in html
    assert "Bypass DSP" in html
    assert "Apply Sound Curve" in html
    assert "Reset Flat" in html

    # Pre-Amp slider
    assert 'id="preAmpSlider"' in html
    assert 'id="preAmpValueText"' in html
    assert "-1.5 dB" in html

    # 10 frequency bands
    for freq in ["32Hz", "64Hz", "125Hz", "250Hz", "500Hz", "1kHz", "2kHz", "4kHz", "8kHz", "16kHz"]:
        assert freq in html

    # Presets
    assert "My Custom Warm Vibe" in html
    assert "Bass Bump" in html
    assert "Vocal Sparkle" in html
    assert "Flat Studio" in html
    assert "Analog Tape Reel" in html

    # Spline SVG & interactive nodes
    assert 'id="eqCurvePath"' in html
    assert 'id="eqAreaPath"' in html
    assert 'id="nodesLayer"' in html


def test_smart_playlist_creator_two_column_layout(wiring_env):
    """Verify 2-column layout with Cassette Deck, Harmonic Flow Arc, and DNA gauges."""
    import json
    from vibeplay.db import get_connection, insert_track, insert_or_replace_features

    db_file, client = wiring_env

    # Insert sample tracks with features into DB for generation
    with get_connection(db_file) as conn:
        t1 = insert_track(
            conn,
            path="/music/artist/album/01.flac",
            title="Track 01",
            artist="Artist",
            album="Album",
            duration=200,
            mtime=1.0,
            size=1000,
            file_hash="hash1",
        )
        insert_or_replace_features(
            conn,
            track_id=t1,
            analyzer_version="1.0.0",
            bpm=120.0,
            key="A",
            scale="minor",
            loudness=-8.0,
            danceability=0.7,
            energy=0.6,
            mood_scores_json=json.dumps({"happy": 0.5}),
            embedding_blob=b"\x00" * 32,
        )
        t2 = insert_track(
            conn,
            path="/music/artist/album/02.flac",
            title="Track 02",
            artist="Artist",
            album="Album",
            duration=210,
            mtime=1.0,
            size=1000,
            file_hash="hash2",
        )
        insert_or_replace_features(
            conn,
            track_id=t2,
            analyzer_version="1.0.0",
            bpm=124.0,
            key="C",
            scale="major",
            loudness=-7.5,
            danceability=0.75,
            energy=0.7,
            mood_scores_json=json.dumps({"happy": 0.6}),
            embedding_blob=b"\x00" * 32,
        )

    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # Vibe Synthesizer Hero Deck
    assert "Tell me what you want to hear" in html
    assert "VIBE ENGINE v4.2" in html
    assert "Cook Up Mixtape" in html

    # Stepper navigation
    assert 'id="pill-step-1"' in html
    assert 'id="pill-step-2"' in html
    assert 'id="pill-step-3"' in html
    assert 'id="pill-step-4"' in html

    # Preview generated sequence with 2-column layout
    gen_resp = client.post(
        "/api/playlist/builder/preview",
        data={"seed_track_id": str(t1), "arc": "energy_ramp", "name": "Test Mixtape", "limit": "2", "max_bpm_delta": "10"}
    )
    assert gen_resp.status_code == 200
    gen_html = gen_resp.text

    # Cassette Deck Reel preview card
    assert "Mixtape Deck Reel" in gen_html
    assert "Lossless Bitstream" in gen_html
    assert "SIDE A •" in gen_html
    assert "Type IV Metal" in gen_html

    # Harmonic Flow Arc SVG
    assert "Harmonic Flow Arc" in gen_html
    assert 'id="curveGradient"' in gen_html
    assert 'id="areaGradient"' in gen_html

    # Acoustic DNA Balance Gauges
    assert "Acoustic DNA Balance" in gen_html
    assert "Distortion &amp; Energy" in gen_html or "Distortion & Energy" in gen_html
    assert "Tempo Punch &amp; Rhythm" in gen_html or "Tempo Punch & Rhythm" in gen_html
    assert "Vocal Forwardness" in gen_html
    assert "Analog Tape Warmth" in gen_html


def test_dynamic_dac_output_routing_and_oob_swap(client: TestClient):
    """Verify dynamic DAC routing and out-of-band swap updates."""
    # Test GET outputs
    resp = client.get("/api/player/output/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert "profiles" in data
    assert len(data["profiles"]) > 0

    # Test POST output switch
    switch_resp = client.post("/api/player/output", data={"profile": "Direct ALSA (hw:0,0)"})
    assert switch_resp.status_code == 200
    switch_html = switch_resp.text

    # Transport footer receives updated profile
    assert "Direct ALSA (hw:0,0)" in switch_html

    # Out-of-band swap for header playing-on text
    assert 'id="header-playing-on-text"' in switch_html
    assert 'hx-swap-oob="true"' in switch_html


def test_all_template_onclick_handlers_exist_in_app_js():
    """Verify that every onclick/oninput function called in templates exists and is defined in app.js."""
    template_dir = Path("src/vibeplay/templates")
    html_files = list(template_dir.rglob("*.html"))
    js_content = Path("src/vibeplay/static/app.js").read_text()

    # Regex for onclick="funcName(...)" or oninput="funcName(...)"
    handler_pattern = re.compile(r'on(?:click|input|change|submit)="([a-zA-Z0-9_]+)\(')
    called_functions = set()

    # Ignore inline language constructs and browser built-ins
    builtins = {
        "this", "event", "alert", "confirm", "prompt", "parseInt", "parseFloat",
        "switchLibraryView", "syncBpmSlider", "updateSliderLabel", "if"
    }

    for hf in html_files:
        content = hf.read_text()
        for match in handler_pattern.finditer(content):
            fn = match.group(1)
            if fn not in builtins and not fn.startswith("console"):
                called_functions.add(fn)

    missing = []
    for fn in called_functions:
        # Check if function is declared: function fnName( or window.fnName = or const fnName =
        if not (
            f"function {fn}" in js_content
            or f"window.{fn}" in js_content
            or f"{fn} = function" in js_content
            or f"const {fn} =" in js_content
            or f"let {fn} =" in js_content
            or f"var {fn} =" in js_content
        ):
            missing.append(fn)

    assert not missing, f"The following functions are called in templates but missing from app.js: {missing}"


def test_lofi_lounge_hero_sections_and_crate_wiring(wiring_env):
    """Verify Lo-Fi Lounge hero turntable, crate shelves 01 & 02, and lounge listeners."""
    from vibeplay.db import get_connection, insert_track, insert_or_replace_features

    db_file, client = wiring_env

    with get_connection(db_file) as conn:
        t1 = insert_track(
            conn,
            path="/music/jazz/01_rainy_kissa.flac",
            title="Rainy Kissa Midnight",
            artist="Ryo Trio",
            album="Tokyo Kissa Sessions",
            duration=240,
            mtime=1.0,
            size=5000,
            file_hash="hash_kissa_1",
        )
        insert_or_replace_features(
            conn,
            track_id=t1,
            analyzer_version="1.0.0",
            bpm=88.0,
            key="A",
            scale="minor",
            loudness=-9.0,
            danceability=0.6,
            energy=0.45,
            mood_scores_json="{}",
            embedding_blob=b"\x00" * 32,
        )

    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Main Lofi Lounge Deck Container
    assert "lofi-lounge-deck" in html
    assert "hero-turntable-deck" in html or "turntable-vinyl-container" in html
    assert "turntable-spinning-disc" in html
    assert "turntable-tonearm" in html

    # 2. Tactile Hi-Fi Potentiometers & DSP
    assert "Tactile Hi-Fi Potentiometers" in html
    assert "Tube Warmth" in html
    assert "Master Gain" in html
    assert "Acoustic Room &amp; DSP" in html or "Acoustic Room & DSP" in html

    # 3. Crate Shelf 01 with vinyl sleeve and peeking disc
    assert "Crate Shelf 01" in html
    assert "Warm Analog Tapes &amp; Late Night Jazz" in html or "Warm Analog Tapes & Late Night Jazz" in html
    assert "vinyl-sleeve-card" in html
    assert "vinyl-disc-peeking" in html
    assert f'hx-post="/api/player/play-track/{t1}"' in html
    assert 'hx-target="#transport-footer-container"' in html

    # 4. Crate Shelf 02 (Continuous Stream Deck)
    assert "Crate Shelf 02" in html
    assert "Continuous Stream Deck" in html
    assert "Lo-Fi Chillhop &amp; Synth Breezes" in html or "Lo-Fi Chillhop & Synth Breezes" in html
    assert "stream-track-row" in html
    assert "Rainy Kissa Midnight" in html
    assert "Ryo Trio" in html

    # 5. Lounge Listeners (Social Crate Deck)
    assert "Social Crate Deck" in html
    assert "Lounge Listeners" in html
    assert "Currently in the Lounge" in html
    assert "Yuki M." in html
    assert "Sennheiser HD600" in html
    assert "Marcus L." in html
    assert "Audeze LCD-2" in html
    assert "Elena S." in html
    assert "Focal Clear" in html
    assert "Share Deck Sync URL" in html

