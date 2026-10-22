"""Theme engine and palette presets for the vibeplay desktop console."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ThemePreset:
    """Color palette and CSS custom properties definition for an app theme."""

    id: str
    name: str
    description: str
    variables: dict[str, str] = field(default_factory=dict)


THEME_PRESETS: list[ThemePreset] = [
    ThemePreset(
        id="god-of-ink",
        name="God of Ink",
        description="Deep midnight navy, slate surfaces, and luminous periwinkle accents",
        variables={
            "--bg-base": "#070b14",
            "--bg-surface": "#0f172a",
            "--bg-card": "#1e293b",
            "--border": "#334155",
            "--border-subtle": "#1e293b",
            "--text": "#f8fafc",
            "--text-muted": "#94a3b8",
            "--primary": "#6366f1",
            "--primary-hover": "#4f46e5",
            "--accent": "#38bdf8",
            "--status-ok": "#22c55e",
            "--status-warn": "#eab308",
            "--status-err": "#ef4444",
        },
    ),
    ThemePreset(
        id="wine",
        name="Wine",
        description="Merlot undertones, rich velvet charcoal, and uncut rose-amethyst highlights",
        variables={
            "--bg-base": "#12050b",
            "--bg-surface": "#230b17",
            "--bg-card": "#3b1427",
            "--border": "#5c1d3d",
            "--border-subtle": "#2e0f1f",
            "--text": "#fff1f2",
            "--text-muted": "#fda4af",
            "--primary": "#e11d48",
            "--primary-hover": "#be123c",
            "--accent": "#fb7185",
            "--status-ok": "#10b981",
            "--status-warn": "#f59e0b",
            "--status-err": "#f43f5e",
        },
    ),
    ThemePreset(
        id="obsidian",
        name="Obsidian",
        description="Jet-black foundation, dark violet layers, and delicate lavender glow",
        variables={
            "--bg-base": "#050308",
            "--bg-surface": "#120a1c",
            "--bg-card": "#1d122e",
            "--border": "#3b235d",
            "--border-subtle": "#1b0f2a",
            "--text": "#faf5ff",
            "--text-muted": "#d8b4fe",
            "--primary": "#a855f7",
            "--primary-hover": "#9333ea",
            "--accent": "#c084fc",
            "--status-ok": "#22c55e",
            "--status-warn": "#eab308",
            "--status-err": "#ef4444",
        },
    ),
    ThemePreset(
        id="swimming-with-the-whales",
        name="Swimming with the Whales",
        description="Abyssal ocean depths, cobalt consoles, and oceanic turquoise energy",
        variables={
            "--bg-base": "#030c17",
            "--bg-surface": "#0a1e36",
            "--bg-card": "#113259",
            "--border": "#1b4d8a",
            "--border-subtle": "#0e294b",
            "--text": "#f0f9ff",
            "--text-muted": "#7dd3fc",
            "--primary": "#0284c7",
            "--primary-hover": "#0369a1",
            "--accent": "#38bdf8",
            "--status-ok": "#10b981",
            "--status-warn": "#f59e0b",
            "--status-err": "#ef4444",
        },
    ),
    ThemePreset(
        id="mint-city",
        name="Mint City",
        description="Dark plum chassis, deep industrial teal, and crisp neon-mint highlights",
        variables={
            "--bg-base": "#091212",
            "--bg-surface": "#102324",
            "--bg-card": "#17383a",
            "--border": "#215356",
            "--border-subtle": "#122d2f",
            "--text": "#f0fdfa",
            "--text-muted": "#5eead4",
            "--primary": "#14b8a6",
            "--primary-hover": "#0d9488",
            "--accent": "#2dd4bf",
            "--status-ok": "#22c55e",
            "--status-warn": "#f59e0b",
            "--status-err": "#ef4444",
        },
    ),
    ThemePreset(
        id="slate-audiophile",
        name="Slate Audiophile",
        description="Classic high-contrast dark console with emerald status indicators",
        variables={
            "--bg-base": "#0f1115",
            "--bg-surface": "#181a20",
            "--bg-card": "#22252c",
            "--border": "#313540",
            "--border-subtle": "#1d2026",
            "--text": "#f3f4f6",
            "--text-muted": "#9ca3af",
            "--primary": "#10b981",
            "--primary-hover": "#059669",
            "--accent": "#34d399",
            "--status-ok": "#10b981",
            "--status-warn": "#f59e0b",
            "--status-err": "#ef4444",
        },
    ),
]


def get_available_themes() -> list[ThemePreset]:
    """Retrieve all defined theme presets."""
    return THEME_PRESETS


def get_theme_by_id(theme_id: str) -> ThemePreset:
    """Retrieve theme preset by identifier, defaulting to 'god-of-ink' if not found."""
    clean_id = theme_id.lower().strip()
    if clean_id == "slate-classic":
        clean_id = "slate-audiophile"
    for preset in THEME_PRESETS:
        if preset.id == clean_id:
            return preset
    return THEME_PRESETS[0]


def get_theme_css_variables(theme_id: str = "god-of-ink") -> str:
    """Generate CSS variable declarations string for a target theme."""
    theme = get_theme_by_id(theme_id)
    declarations = [f"  {k}: {v};" for k, v in theme.variables.items()]
    # Add mapped aliases for styles.html compatibility
    declarations.extend([
        f"  --bg-canvas: {theme.variables.get('--bg-base', '#070b14')};",
        f"  --bg-container-lowest: {theme.variables.get('--bg-base', '#070b14')};",
        f"  --bg-container-low: {theme.variables.get('--bg-surface', '#0f172a')};",
        f"  --bg-container: {theme.variables.get('--bg-card', '#1e293b')};",
        f"  --bg-container-high: {theme.variables.get('--border', '#334155')};",
        f"  --text-primary: {theme.variables.get('--text', '#f8fafc')};",
        f"  --secondary: {theme.variables.get('--accent', '#38bdf8')};",
        f"  --tertiary: {theme.variables.get('--status-ok', '#22c55e')};",
    ])
    return f":root[data-theme='{theme.id}'], html[data-theme='{theme.id}'], body[data-theme='{theme.id}'] {{\n" + "\n".join(declarations) + "\n}"


def generate_all_themes_css() -> str:
    """Generate complete CSS stylesheet declaring custom properties for all presets."""
    blocks = [get_theme_css_variables("god-of-ink")]
    for preset in THEME_PRESETS:
        blocks.append(get_theme_css_variables(preset.id))
    return "\n\n".join(blocks)

