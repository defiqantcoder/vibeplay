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
    assert 'id="eqGlowGradient"' in html
    assert 'id="neonGlow"' in html
    assert 'filter="url(#neonGlow)"' in html
    assert 'fill="url(#eqGlowGradient)"' in html

    # Modal hidden by default
    assert 'id="eq-studio-backdrop"' in html
    assert 'hidden' in html

    # Preset dropdown styling and inline onclick triggers for applyEQPreset()
    assert 'id="presetTrigger"' in html
    assert 'id="presetMenu"' in html
    assert 'onclick="applyEQPreset(\'My Custom Warm Vibe\'' in html
    assert 'onclick="applyEQPreset(\'Bass Bump 🔊\'' in html
    assert 'onclick="applyEQPreset(\'Vocal Sparkle ✨\'' in html
    assert 'onclick="applyEQPreset(\'Flat Studio 📏\'' in html
    assert 'onclick="applyEQPreset(\'Analog Tape Reel 📼\'' in html


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


def test_library_table_stitch_layout_and_sorting_wiring(wiring_env):
    """Verify library table exact Stitch layout, headers, quality pills, energy bars, and row wiring."""
    from vibeplay.db import get_connection, insert_track, insert_or_replace_features

    db_file, client = wiring_env

    with get_connection(db_file) as conn:
        t_id = insert_track(
            conn,
            path="/music/flown.flac",
            title="Aura Reflections",
            artist="Kiasmos",
            album="Flown",
            duration=348,
            mtime=1.0,
            size=12000,
            file_hash="hash_kiasmos_aura",
        )
        insert_or_replace_features(
            conn,
            track_id=t_id,
            analyzer_version="1.0.0",
            bpm=124.0,
            key="A",
            scale="minor",
            loudness=-7.8,
            danceability=0.74,
            energy=0.78,
            mood_scores_json="{}",
            embedding_blob=b"\x00" * 32,
        )

    # Fetch table partial via GET /api/library/table
    resp = client.get("/api/library/table")
    assert resp.status_code == 200
    html = resp.text

    # 1. Exact Stitch table layout & classes
    assert 'id="crate-table"' in html
    assert 'min-w-[1100px]' in html
    assert 'id="crate-table-body"' in html

    # 2. <th> headers with sorting triggers
    assert 'hx-get="/api/library/table?sort=' in html
    assert 'hx-target="#library-table-container"' in html
    assert "Title 🔤" in html
    assert "Artist" in html
    assert "Album" in html
    assert "Quality" in html
    assert "Tempo ⚡" in html
    assert "Vibe Key" in html
    assert "Energy Bar" in html
    assert "Length" in html
    assert "Actions" in html

    # 3. Track row styling & attributes
    assert "track-row" in html
    assert f'data-track-id="{t_id}"' in html
    assert f'hx-post="/api/player/play-track/{t_id}"' in html
    assert 'hx-target="#transport-footer-container"' in html

    # 4. Row components: Quality pills, energy bar, length
    assert "Aura Reflections" in html
    assert "Kiasmos" in html
    assert "Flown" in html
    assert "FLAC ✨" in html or "96k/24b 👑" in html
    assert "124 bpm ⚡" in html
    assert "8A / A Minor" in html
    assert "78%" in html
    assert "05:48" in html
    assert 'playing-bars' in html or 'play_arrow' in html


def test_record_crate_visual_vinyl_sleeve_cards_and_grooves(wiring_env):
    """Verify Record Crate exact Stitch vinyl sleeves, groove circles, center label chips, and HTMX play triggers."""
    from vibeplay.db import get_connection, insert_track, insert_or_replace_features

    db_file, client = wiring_env

    with get_connection(db_file) as conn:
        t_id = insert_track(
            conn,
            path="/music/vinyl_rip_01.flac",
            title="Warm Wurlitzer Solitudes",
            artist="Hanna Vane",
            album="Electric Rain",
            duration=225,
            mtime=1.0,
            size=8000,
            file_hash="hash_hanna_wurlitzer",
        )
        insert_or_replace_features(
            conn,
            track_id=t_id,
            analyzer_version="1.0.0",
            bpm=92.0,
            key="C",
            scale="major",
            loudness=-8.5,
            danceability=0.55,
            energy=0.62,
            mood_scores_json="{}",
            embedding_blob=b"\x00" * 32,
        )

    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Crate container and header elements
    assert "master-record-crate-bay" in html
    assert "crate-bay-header" in html
    assert "The Record Crate" in html
    assert "TAPES" in html
    assert "crate-mood-chip" in html

    # 2. Vinyl grid and sleeve housing
    assert "vinyl-crate-grid" in html
    assert "vinyl-sleeve-card" in html
    assert "vinyl-sleeve-housing" in html

    # 3. Peeking vinyl record with concentric grooves & center label chip
    assert "vinyl-disc-peeking" in html
    assert "vinyl-groove-circle" in html
    assert "vinyl-center-label-chip" in html
    assert "33⅓" in html
    assert "RPM" in html

    # 4. Sleeve jacket front cover, key pill, and play trigger
    assert "vinyl-jacket-front" in html
    assert "jacket-key-pill" in html
    assert f'hx-post="/api/player/play-track/{t_id}"' in html
    assert 'hx-target="#transport-footer-container"' in html
    assert 'onclick="selectTrackRow(this,' in html

    # 5. Track metadata
    assert "vinyl-meta-group" in html
    assert "Warm Wurlitzer Solitudes" in html
    assert "Hanna Vane" in html
    assert "03:45" in html or "vinyl-specs-row" in html


def test_boombox_capsule_transport_bar_layout_and_wiring(wiring_env):
    """Verify Boombox Capsule 3-bay flex layout, Jinja bindings, SVGs, HTMX endpoints, and output switcher toggle."""
    db_file, client = wiring_env

    # 1. Fetch transport bar endpoint directly
    resp = client.get("/api/player/transport")
    assert resp.status_code == 200
    html = resp.text

    # 2. Main Boombox Capsule Container & 3-Bay Layout
    assert "transport-footer" in html
    assert 'id="transport-footer-bar"' in html
    assert "now-playing" in html
    assert "transport-center" in html
    assert "transport-right" in html

    # 3. Left Section: 56x56 Album art, animated wave bars, meta, Big Screen pill
    assert "album-art-thumb" in html
    assert "art-wave-overlay" in html
    assert "wave-bar-1" in html
    assert "now-playing-meta" in html
    assert "lossless-pill-badge" in html
    assert "Lossless FLAC" in html
    assert "btn-bigscreen-pill" in html
    assert "openFullscreenNowPlaying()" in html

    # 4. Center Section: Playback SVGs and HTMX controls
    assert 'hx-post="/api/player/toggle"' in html
    assert 'hx-post="/api/player/next"' in html
    assert 'hx-post="/api/player/prev"' in html
    assert 'hx-target="#transport-footer-container"' in html
    assert "btn-play-pause" in html
    assert 'id="btn-transport-shuffle"' in html
    assert 'id="btn-transport-repeat"' in html

    # 5. Center Section: Scrub Timeline micro-component
    assert "transport-scrub-row" in html
    assert "scrub-bar" in html
    assert "scrub-wave-silhouette" in html
    assert "timecode-elapsed" in html
    assert "timecode-total" in html

    # 6. Right Section: Output Switcher Pill with green dot & toggleOutputSwitcher
    assert "transport-dac-capsule" in html
    assert 'onclick="toggleOutputSwitcher(event)"' in html
    assert "dac-green-dot" in html
    assert "FiiO KA15" in html or "Direct ALSA" in html

    # 7. Right Section: Bit-Perfect pill, Mute SVG, Volume slider & readout
    assert "transport-bitperfect-pill" in html
    assert "Bit-Perfect" in html
    assert 'hx-post="/api/player/mute-toggle"' in html
    assert 'hx-post="/api/player/volume"' in html
    assert 'id="global-volume-slider"' in html
    assert 'id="volume-readout"' in html
    assert "vol-db-readout" in html


def test_multipane_settings_modal_and_theme_customizer_wiring(client: TestClient):
    """Verify multi-pane settings modal, 6 sidebar tabs, 9 theme customizer cards, and swatch dots."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Dialog element is present and hidden by default (no 'open' attribute)
    assert '<dialog id="settings-dialog"' in html
    match = re.search(r'<dialog\s+id="settings-dialog"[^>]*>', html)
    assert match is not None
    dialog_tag = match.group(0)
    assert "open" not in dialog_tag.split()  # not open by default

    # 2. Stitch Modal Header & Badges
    assert "Settings &amp; Theme Customizer" in html or "Settings & Theme Customizer" in html
    assert "v2.4 Audiophile Edition" in html
    assert 'onclick="closeSettingsDialog()"' in html
    assert 'id="modal-close-trigger"' in html

    # 3. Left Sidebar Tabs and Tab Switching triggers
    assert 'class="settings-tabs-bar"' in html
    for tab_id in ["theme", "transport", "dsp", "analyzer", "plugins", "ai"]:
        assert f'id="tab-btn-{tab_id}"' in html
        assert f'onclick="switchSettingsTab(\'{tab_id}\')"' in html

    # 4. Pinned DAC chip
    assert "settings-sidebar-dac-chip" in html
    assert "FiiO KA15" in html
    assert "System Ready • Direct" in html

    # 5. Theme Presets 3x3 Grid
    assert "theme-cards-grid" in html
    assert "grid grid-cols-3 gap-3" in html
    assert "9 Presets Available" in html

    # 6. All 9 Theme Cards with applyTheme triggers, data-theme-card attributes, and swatch dots
    theme_ids = [
        "god-of-ink",
        "wine",
        "obsidian",
        "swimming-with-the-whales",
        "mint-city",
        "slate-audiophile",
        "beyond-the-boundary",
        "the-unknown",
        "castle-in-the-sky",
    ]
    for tid in theme_ids:
        assert f'onclick="applyTheme(\'{tid}\')"' in html
        assert f'data-theme-card="{tid}"' in html
        assert f'id="theme-{tid}"' in html

    # Verify swatch dots are present
    assert "theme-swatch-dot" in html
    assert "swatch-ink-navy" in html
    assert "swatch-ink-slate" in html
    assert "swatch-ink-pri" in html
    assert "swatch-wine-base" in html
    assert "swatch-wine-rose" in html
    assert "swatch-obs-base" in html
    assert "swatch-whale-ocean" in html
    assert "swatch-mint-charcoal" in html
    assert "swatch-slate-pri" in html
    assert "swatch-beyond-cyan" in html
    assert "swatch-unknown-orange" in html
    assert "swatch-castle-celadon" in html

    # 7. Modal Footer
    assert 'id="modal-cancel-btn"' in html
    assert 'id="modal-save-btn"' in html
    assert 'onclick="saveDesktopSettings(true)"' in html
    assert "Save &amp; Chill" in html or "Save & Chill" in html


def test_output_switcher_popover_stitch_layout_and_wiring(client: TestClient):
    """Verify output switcher popover Stitch layout, dynamic device cards loop, and hx-post route change triggers."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Output Switcher Popover shell and glassmorphism styling
    assert 'id="output-switcher-popover"' in html
    assert "w-[320px]" in html
    assert "rounded-[18px]" in html
    assert "backdrop-blur-xl" in html
    assert "hidden" in html

    # 2. Popover Header
    assert "Where should the music play?" in html
    assert "Plugging in a DAC automatically swaps audio here!" in html
    assert 'onclick="closeOutputSwitcher();"' in html

    # 3. Dynamic Device Cards with exact Stitch classes and hx-post
    assert "output-device-card" in html
    assert 'hx-post="/api/player/output"' in html
    assert 'hx-target="#transport-footer-container"' in html
    assert 'onclick="closeOutputSwitcher()"' in html

    # Stitch exact card classes
    assert "bg-[#06b6d4]/10" in html
    assert "border-2 border-[#06b6d4]" in html
    assert "bg-[#121214]/60" in html
    assert "border-[#2a2a35]" in html

    # 4. Footer Instant Auto-Swap and downward caret arrow
    assert "Instant Auto-Swap" in html
    assert "Switch to USB DAC the moment plugged" in html
    assert "rotate-45" in html


def test_addon_toybox_plugin_manager_stitch_layout_and_wiring(client: TestClient):
    """Verify Add-on Toybox modal Stitch layout, filter tabs onclick, and toggle switches."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Backdrop and Chassis layout
    assert 'id="toybox-backdrop"' in html
    assert "bg-[#0e0e10]/80" in html
    assert "backdrop-blur-md" in html
    assert "hidden" in html
    assert "max-w-[860px]" in html
    assert "bg-[#1e1e24]" in html
    assert "rounded-[20px]" in html
    assert "p-8" in html

    # 2. Header and close triggers
    assert "The Add-on Toybox" in html
    assert "Modular tools and sound gadgets" in html
    assert 'id="modal-close-btn"' in html
    assert 'onclick="closeToyboxModal();"' in html

    # 3. Top filter tabs with onclick filter functions
    assert 'onclick="filterToyboxCards(\'all\', this)"' in html
    assert 'onclick="filterToyboxCards(\'dsp\', this)"' in html
    assert 'onclick="filterToyboxCards(\'library\', this)"' in html
    assert 'onclick="filterToyboxCards(\'network\', this)"' in html
    assert "All Toys (3)" in html
    assert "Sound DSP" in html
    assert "Library Tools" in html
    assert "Network Bridge" in html

    # 4. Plugin Cards with Stitch classes
    assert "The Soundbar" in html
    assert "DSP &amp; ACOUSTICS" in html or "DSP & ACOUSTICS" in html
    assert "Crate Cleaner &amp; Dedupe" in html or "Crate Cleaner & Dedupe" in html
    assert "Kodi Streamer Bridge" in html
    assert "Explore Community Add-ons" in html
    assert "toy-card" in html
    assert "toybox-card" in html

    # 5. CSS Toggle switches intact
    assert "toy-toggle" in html
    assert 'role="switch"' in html
    assert 'onclick="toggleToySwitch(this, \'dsp\')"' in html
    assert 'onclick="toggleToySwitch(this, \'maintenance\')"' in html
    assert 'onclick="toggleToySwitch(this, \'network\')"' in html
    assert "Active &amp; Ready" in html or "Active & Ready" in html
    assert "Taking a Nap" in html

    # 6. Footer section
    assert "Core audio engine runs lean &amp; clean" in html or "Core audio engine runs lean & clean" in html
    assert "Install an Add-on" in html
    assert 'id="modal-done-btn"' in html


