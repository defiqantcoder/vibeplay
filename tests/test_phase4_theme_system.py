"""Tests for Phase 4: Theme System and Visual Identity."""

from __future__ import annotations

from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from vibeplay.config import Settings
from vibeplay.db import get_connection, init_db
from vibeplay.desktop.settings import save_desktop_settings, DesktopSettings
from vibeplay.ui.theme import (
    DEFAULT_THEME_ID,
    THEME_PRESETS,
    compute_contrast_ratio,
    compute_relative_luminance,
    generate_all_themes_css,
    get_available_themes,
    get_theme_by_id,
    get_theme_css_variables,
    verify_theme_contrast,
)
from vibeplay.web import create_app


@pytest.fixture()
def phase4_env(tmp_path: Path):
    """Create an isolated test environment with seeded tracks and isolated settings."""
    db_path = tmp_path / "phase4_test.db"
    settings_path = tmp_path / "desktop_settings.json"
    init_db(db_path)
    cfg = Settings(db_path=db_path, desktop_settings_path=settings_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tracks (id, path, mtime, size, hash, duration, title, artist, album, status)
            VALUES (1, '/music/ink.flac', 1700000000.0, 5000, 'hash_phase4_1', 245.0, 'Midnight Ink', 'Aether Ensemble', 'God of Ink', 'active')
            """
        )
        conn.execute(
            """
            INSERT INTO features (track_id, bpm, key, scale, energy, danceability, loudness, mood_scores, analyzer_version)
            VALUES (1, 118.0, 'A', 'minor', 0.72, 0.65, -14.2, '{"relaxed": 0.85, "electronic": 0.75}', '2.0')
            """
        )
        conn.commit()
    app = create_app(db_path=db_path, settings=cfg)
    client = TestClient(app)
    return client, cfg, settings_path


def test_phase4_theme_presets_and_named_subpalettes():
    """Verify all Phase 4 themes and their required named sub-palette swatches exist."""
    presets = {t.id: t for t in get_available_themes()}
    assert len(presets) == 6

    # 1. God of Ink: Navy, Slate, Periwinkle
    ink = presets["god-of-ink"]
    assert ink.name == "God of Ink"
    for swatch_name in ("Navy", "Slate", "Periwinkle"):
        assert swatch_name in ink.swatches
        assert ink.swatches[swatch_name].startswith("#")

    # 2. Wine: Uncut Amethyst
    wine = presets["wine"]
    assert wine.name == "Wine"
    assert "Uncut Amethyst" in wine.swatches
    assert wine.swatches["Uncut Amethyst"].startswith("#")

    # 3. Obsidian: Purple, Lavender
    obsidian = presets["obsidian"]
    assert obsidian.name == "Obsidian"
    for swatch_name in ("Purple", "Lavender"):
        assert swatch_name in obsidian.swatches
        assert obsidian.swatches[swatch_name].startswith("#")

    # 4. Swimming with the Whales: Ocean, Cobalt, Blue
    whales = presets["swimming-with-the-whales"]
    assert whales.name == "Swimming with the Whales"
    for swatch_name in ("Ocean", "Cobalt", "Blue"):
        assert swatch_name in whales.swatches
        assert whales.swatches[swatch_name].startswith("#")

    # 5. Mint City: Plum, Charcoal, Teal, Mint
    mint = presets["mint-city"]
    assert mint.name == "Mint City"
    for swatch_name in ("Plum", "Charcoal", "Teal", "Mint"):
        assert swatch_name in mint.swatches
        assert mint.swatches[swatch_name].startswith("#")


@pytest.mark.parametrize(
    ("alias", "expected_id"),
    [
        ("navy", "god-of-ink"),
        ("slate", "god-of-ink"),
        ("periwinkle", "god-of-ink"),
        ("uncut-amethyst", "wine"),
        ("Uncut Amethyst", "wine"),
        ("purple", "obsidian"),
        ("lavender", "obsidian"),
        ("ocean", "swimming-with-the-whales"),
        ("cobalt", "swimming-with-the-whales"),
        ("blue", "swimming-with-the-whales"),
        ("plum", "mint-city"),
        ("charcoal", "mint-city"),
        ("teal", "mint-city"),
        ("mint", "mint-city"),
        ("nonexistent-theme", DEFAULT_THEME_ID),
    ],
)
def test_subpalette_alias_resolution(alias: str, expected_id: str):
    """Verify sub-palette swatch names resolve to their parent ThemePreset."""
    resolved = get_theme_by_id(alias)
    assert resolved.id == expected_id


def test_all_themes_define_complete_surface_custom_properties():
    """Verify every theme preset defines the full set of CSS custom properties."""
    required_vars = {
        "--bg-canvas",
        "--bg-surface",
        "--bg-container-lowest",
        "--bg-container-low",
        "--bg-container",
        "--bg-container-high",
        "--bg-container-highest",
        "--bg-titlebar",
        "--bg-menu",
        "--bg-menu-hover",
        "--bg-transport",
        "--surface-tint-subtle",
        "--primary",
        "--primary-glow",
        "--primary-tint",
        "--primary-border",
        "--on-primary",
        "--secondary",
        "--secondary-glow",
        "--secondary-tint",
        "--secondary-border",
        "--tertiary",
        "--tertiary-glow",
        "--tertiary-tint",
        "--tertiary-border",
        "--accent",
        "--error",
        "--error-tint",
        "--error-border",
        "--danger-hover-bg",
        "--danger-hover-text",
        "--text-primary",
        "--text-secondary",
        "--text-muted",
        "--text-dim",
        "--border-subtle",
        "--border-strong",
        "--border-divider",
    }
    all_css = generate_all_themes_css()
    for preset in THEME_PRESETS:
        missing = required_vars - set(preset.variables.keys())
        assert not missing, f"Theme {preset.id} is missing CSS variables: {missing}"
        css_block = get_theme_css_variables(preset.id)
        assert f":root[data-theme='{preset.id}']" in css_block
        assert f":root[data-theme='{preset.id}']" in all_css
        for var_name in required_vars:
            assert f"{var_name}:" in css_block


def test_wcag_contrast_preserved_across_all_themes():
    """Verify labels, buttons, menu bars, and status indicators meet WCAG contrast in every theme."""
    assert compute_relative_luminance("#000000") == pytest.approx(0.0)
    assert compute_relative_luminance("#ffffff") == pytest.approx(1.0)
    assert compute_contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)

    for preset in THEME_PRESETS:
        ratios = verify_theme_contrast(preset.id)
        # Primary text on base and surface >= 7.0 (AAA)
        assert ratios["text_on_base"] >= 7.0, (
            f"{preset.id} primary text on base contrast too low: {ratios['text_on_base']:.2f}"
        )
        assert ratios["text_on_surface"] >= 7.0, (
            f"{preset.id} primary text on surface contrast too low: {ratios['text_on_surface']:.2f}"
        )
        assert ratios["text_on_menu"] >= 7.0, (
            f"{preset.id} primary text on menu contrast too low: {ratios['text_on_menu']:.2f}"
        )
        # Muted text on base and surface >= 4.5 (AA)
        assert ratios["muted_on_base"] >= 4.5, (
            f"{preset.id} muted text on base contrast too low: {ratios['muted_on_base']:.2f}"
        )
        assert ratios["muted_on_surface"] >= 4.5, (
            f"{preset.id} muted text on surface contrast too low: {ratios['muted_on_surface']:.2f}"
        )
        # Primary button text (--on-primary) on --primary background >= 4.5 (AA)
        assert ratios["button_on_primary"] >= 4.5, (
            f"{preset.id} button text on primary contrast too low: {ratios['button_on_primary']:.2f}"
        )
        # Status indicators on surface >= 3.0 (WCAG UI component & graphical object threshold)
        assert ratios["status_ok_on_surface"] >= 3.0, (
            f"{preset.id} ok status contrast too low: {ratios['status_ok_on_surface']:.2f}"
        )
        assert ratios["status_warn_on_surface"] >= 3.0, (
            f"{preset.id} warn status contrast too low: {ratios['status_warn_on_surface']:.2f}"
        )
        assert ratios["status_err_on_surface"] >= 3.0, (
            f"{preset.id} err status contrast too low: {ratios['status_err_on_surface']:.2f}"
        )


def test_root_data_theme_and_api_themes_endpoint(phase4_env):
    """Verify root data-theme attribute renders from settings and /api/themes exposes swatches."""
    client, _cfg, settings_path = phase4_env

    # Default theme is god-of-ink
    res = client.get("/")
    assert res.status_code == 200
    assert 'data-theme="god-of-ink"' in res.text
    assert 'data-contrast="standard"' in res.text

    # Switch persisted theme to Mint City + high-contrast and verify root attributes update
    save_desktop_settings(
        DesktopSettings(theme_id="mint-city", contrast_mode="high-contrast"),
        path=settings_path,
    )
    res_mint = client.get("/")
    assert res_mint.status_code == 200
    assert 'data-theme="mint-city"' in res_mint.text
    assert 'data-contrast="high-contrast"' in res_mint.text

    # Verify /api/themes includes swatches and variables
    themes_res = client.get("/api/themes")
    assert themes_res.status_code == 200
    payload = themes_res.json()
    assert isinstance(payload, list)
    assert len(payload) == 6
    assert payload[0]["id"] == "god-of-ink"
    themes_by_id = {t["id"]: t for t in payload}
    assert "Navy" in themes_by_id["god-of-ink"]["swatches"]
    assert "Uncut Amethyst" in themes_by_id["wine"]["swatches"]
    assert "Lavender" in themes_by_id["obsidian"]["swatches"]
    assert "Cobalt" in themes_by_id["swimming-with-the-whales"]["swatches"]
    assert "Plum" in themes_by_id["mint-city"]["swatches"]


def test_no_hardcoded_colors_in_css_or_app_shell():
    """Verify zero hardcoded colors remain in CSS rules or HTML templates outside --* definitions."""
    repo_root = Path(__file__).resolve().parent.parent
    css_files = [
        repo_root / "src/vibeplay/templates/components/styles.html",
        repo_root / "src/vibeplay/static/style.css",
    ]

    color_literal_re = re.compile(
        r"(#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\(|(?<![\w-])(?:white|black)(?![\w-]))",
        re.IGNORECASE,
    )

    for css_file in css_files:
        content = css_file.read_text(encoding="utf-8")
        # Strip CSS comments
        content_no_comments = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        for line_no, raw_line in enumerate(content_no_comments.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("--"):
                continue
            match = color_literal_re.search(line)
            assert match is None, (
                f"Hardcoded color '{match.group(0)}' found outside CSS custom property "
                f"in {css_file.name}:{line_no} -> {line}"
            )

    # Also scan all HTML templates (excluding styles.html) for inline style color literals
    templates_dir = repo_root / "src/vibeplay/templates"
    inline_style_re = re.compile(r'style="([^"]*)"', re.IGNORECASE)
    for html_file in sorted(templates_dir.rglob("*.html")):
        if html_file.name == "styles.html":
            continue
        html_content = html_file.read_text(encoding="utf-8")
        for match in inline_style_re.finditer(html_content):
            style_val = match.group(1)
            color_match = color_literal_re.search(style_val)
            assert color_match is None, (
                f"Hardcoded inline style color '{color_match.group(0)}' in {html_file.name}: "
                f'style="{style_val}"'
            )
