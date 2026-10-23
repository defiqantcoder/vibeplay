"""Theme engine, palette presets, and WCAG contrast verification for the vibeplay desktop console."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_THEME_ID = "god-of-ink"


@dataclass
class ThemePreset:
    """Color palette, named swatches, and CSS custom properties definition for an app theme."""

    id: str
    name: str
    description: str
    swatches: dict[str, str] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)


THEME_PRESETS: list[ThemePreset] = [
    ThemePreset(
        id="god-of-ink",
        name="God of Ink",
        description="Utilitarian Studio Standard: Navy substrate, Slate surfaces, and Periwinkle signal focus",
        swatches={
            "Navy": "#181824",
            "Slate": "#232538",
            "Periwinkle": "#6874a6",
        },
        variables={
            "--bg-base": "#181824",
            "--bg-canvas": "#181824",
            "--bg-surface": "#232538",
            "--bg-card": "#1c1e31",
            "--bg-container-lowest": "#0b0d1f",
            "--bg-container-low": "#181a2d",
            "--bg-container": "#1c1e31",
            "--bg-container-high": "#27293c",
            "--bg-container-highest": "#313347",
            "--bg-titlebar": "#111119",
            "--bg-menu": "#232538",
            "--bg-menu-hover": "#383b56",
            "--bg-transport": "rgba(11, 13, 31, 0.95)",
            "--surface-tint-subtle": "rgba(184, 196, 251, 0.04)",
            "--border": "#383b56",
            "--border-strong": "#383b56",
            "--border-subtle": "#27293c",
            "--border-divider": "#2b2d42",
            "--border-focus": "#6874a6",
            "--text": "#ebeff8",
            "--text-primary": "#ebeff8",
            "--text-secondary": "#c6c5d0",
            "--text-muted": "#9ca3af",
            "--text-dim": "#8e95a8",
            "--primary": "#6874a6",
            "--primary-hover": "#505c8c",
            "--on-primary": "#ffffff",
            "--primary-glow": "rgba(104, 116, 166, 0.35)",
            "--primary-tint": "rgba(104, 116, 166, 0.14)",
            "--primary-border": "rgba(104, 116, 166, 0.38)",
            "--secondary": "#b8c4fb",
            "--secondary-glow": "rgba(184, 196, 251, 0.25)",
            "--secondary-tint": "rgba(184, 196, 251, 0.12)",
            "--secondary-border": "rgba(184, 196, 251, 0.32)",
            "--tertiary": "#22c55e",
            "--tertiary-glow": "rgba(34, 197, 94, 0.25)",
            "--tertiary-tint": "rgba(34, 197, 94, 0.12)",
            "--tertiary-border": "rgba(34, 197, 94, 0.32)",
            "--accent": "#b8c4fb",
            "--status-ok": "#22c55e",
            "--status-warn": "#e3c375",
            "--status-err": "#fb7185",
            "--error": "#ffb4ab",
            "--error-tint": "rgba(251, 113, 133, 0.14)",
            "--error-border": "rgba(251, 113, 133, 0.38)",
            "--danger-hover-bg": "rgba(128, 29, 56, 0.35)",
            "--danger-hover-text": "#ff859b",
        },
    ),
    ThemePreset(
        id="wine",
        name="Wine",
        description="Merlot Wine depths, velvet burgundy panels, and Uncut Amethyst highlights",
        swatches={
            "Wine": "#230b17",
            "Uncut Amethyst": "#e11d48",
        },
        variables={
            "--bg-base": "#12050b",
            "--bg-canvas": "#12050b",
            "--bg-surface": "#230b17",
            "--bg-card": "#3b1427",
            "--bg-container-lowest": "#0c0307",
            "--bg-container-low": "#230b17",
            "--bg-container": "#3b1427",
            "--bg-container-high": "#4a1830",
            "--bg-container-highest": "#5c1d3d",
            "--bg-titlebar": "#0d0308",
            "--bg-menu": "#230b17",
            "--bg-menu-hover": "#4a1830",
            "--bg-transport": "rgba(12, 3, 7, 0.95)",
            "--surface-tint-subtle": "rgba(251, 113, 133, 0.05)",
            "--border": "#5c1d3d",
            "--border-strong": "#5c1d3d",
            "--border-subtle": "#2e0f1f",
            "--border-divider": "#3b1427",
            "--border-focus": "#e11d48",
            "--text": "#fff1f2",
            "--text-primary": "#fff1f2",
            "--text-secondary": "#fecdd3",
            "--text-muted": "#fda4af",
            "--text-dim": "#f48a98",
            "--primary": "#e11d48",
            "--primary-hover": "#be123c",
            "--on-primary": "#ffffff",
            "--primary-glow": "rgba(225, 29, 72, 0.35)",
            "--primary-tint": "rgba(225, 29, 72, 0.15)",
            "--primary-border": "rgba(225, 29, 72, 0.38)",
            "--secondary": "#fb7185",
            "--secondary-glow": "rgba(251, 113, 133, 0.25)",
            "--secondary-tint": "rgba(251, 113, 133, 0.14)",
            "--secondary-border": "rgba(251, 113, 133, 0.35)",
            "--tertiary": "#10b981",
            "--tertiary-glow": "rgba(16, 185, 129, 0.25)",
            "--tertiary-tint": "rgba(16, 185, 129, 0.14)",
            "--tertiary-border": "rgba(16, 185, 129, 0.35)",
            "--accent": "#fb7185",
            "--status-ok": "#10b981",
            "--status-warn": "#f59e0b",
            "--status-err": "#fb7185",
            "--error": "#fda4af",
            "--error-tint": "rgba(244, 63, 94, 0.16)",
            "--error-border": "rgba(244, 63, 94, 0.4)",
            "--danger-hover-bg": "rgba(225, 29, 72, 0.3)",
            "--danger-hover-text": "#ffe4e6",
        },
    ),
    ThemePreset(
        id="obsidian",
        name="Obsidian",
        description="Jet-black Obsidian foundation, royal Purple layers, and Lavender glow",
        swatches={
            "Obsidian": "#050308",
            "Purple": "#a855f7",
            "Lavender": "#d8b4fe",
        },
        variables={
            "--bg-base": "#050308",
            "--bg-canvas": "#050308",
            "--bg-surface": "#120a1c",
            "--bg-card": "#1d122e",
            "--bg-container-lowest": "#030205",
            "--bg-container-low": "#120a1c",
            "--bg-container": "#1d122e",
            "--bg-container-high": "#2c1a47",
            "--bg-container-highest": "#3b235d",
            "--bg-titlebar": "#040207",
            "--bg-menu": "#120a1c",
            "--bg-menu-hover": "#2c1a47",
            "--bg-transport": "rgba(3, 2, 5, 0.95)",
            "--surface-tint-subtle": "rgba(216, 180, 254, 0.05)",
            "--border": "#3b235d",
            "--border-strong": "#3b235d",
            "--border-subtle": "#1b0f2a",
            "--border-divider": "#241538",
            "--border-focus": "#a855f7",
            "--text": "#faf5ff",
            "--text-primary": "#faf5ff",
            "--text-secondary": "#e9d5ff",
            "--text-muted": "#d8b4fe",
            "--text-dim": "#b794f4",
            "--primary": "#a855f7",
            "--primary-hover": "#9333ea",
            "--on-primary": "#050308",
            "--primary-glow": "rgba(168, 85, 247, 0.35)",
            "--primary-tint": "rgba(168, 85, 247, 0.15)",
            "--primary-border": "rgba(168, 85, 247, 0.38)",
            "--secondary": "#c084fc",
            "--secondary-glow": "rgba(192, 132, 252, 0.25)",
            "--secondary-tint": "rgba(192, 132, 252, 0.14)",
            "--secondary-border": "rgba(192, 132, 252, 0.35)",
            "--tertiary": "#22c55e",
            "--tertiary-glow": "rgba(34, 197, 94, 0.25)",
            "--tertiary-tint": "rgba(34, 197, 94, 0.14)",
            "--tertiary-border": "rgba(34, 197, 94, 0.35)",
            "--accent": "#c084fc",
            "--status-ok": "#22c55e",
            "--status-warn": "#eab308",
            "--status-err": "#f87171",
            "--error": "#fca5a5",
            "--error-tint": "rgba(239, 68, 68, 0.15)",
            "--error-border": "rgba(239, 68, 68, 0.38)",
            "--danger-hover-bg": "rgba(153, 27, 27, 0.35)",
            "--danger-hover-text": "#fecaca",
        },
    ),
    ThemePreset(
        id="swimming-with-the-whales",
        name="Swimming with the Whales",
        description="Abyssal Ocean depths, Cobalt consoles, and luminous Blue energy",
        swatches={
            "Ocean": "#030c17",
            "Cobalt": "#0a1e36",
            "Blue": "#0284c7",
        },
        variables={
            "--bg-base": "#030c17",
            "--bg-canvas": "#030c17",
            "--bg-surface": "#0a1e36",
            "--bg-card": "#113259",
            "--bg-container-lowest": "#02070e",
            "--bg-container-low": "#0a1e36",
            "--bg-container": "#113259",
            "--bg-container-high": "#163f70",
            "--bg-container-highest": "#1b4d8a",
            "--bg-titlebar": "#020810",
            "--bg-menu": "#0a1e36",
            "--bg-menu-hover": "#163f70",
            "--bg-transport": "rgba(2, 7, 14, 0.95)",
            "--surface-tint-subtle": "rgba(56, 189, 248, 0.05)",
            "--border": "#1b4d8a",
            "--border-strong": "#1b4d8a",
            "--border-subtle": "#0e294b",
            "--border-divider": "#133661",
            "--border-focus": "#0284c7",
            "--text": "#f0f9ff",
            "--text-primary": "#f0f9ff",
            "--text-secondary": "#bae6fd",
            "--text-muted": "#7dd3fc",
            "--text-dim": "#60b8e8",
            "--primary": "#0284c7",
            "--primary-hover": "#0369a1",
            "--on-primary": "#030c17",
            "--primary-glow": "rgba(2, 132, 199, 0.35)",
            "--primary-tint": "rgba(2, 132, 199, 0.16)",
            "--primary-border": "rgba(56, 189, 248, 0.35)",
            "--secondary": "#38bdf8",
            "--secondary-glow": "rgba(56, 189, 248, 0.25)",
            "--secondary-tint": "rgba(56, 189, 248, 0.14)",
            "--secondary-border": "rgba(56, 189, 248, 0.35)",
            "--tertiary": "#10b981",
            "--tertiary-glow": "rgba(16, 185, 129, 0.25)",
            "--tertiary-tint": "rgba(16, 185, 129, 0.14)",
            "--tertiary-border": "rgba(16, 185, 129, 0.35)",
            "--accent": "#38bdf8",
            "--status-ok": "#10b981",
            "--status-warn": "#f59e0b",
            "--status-err": "#f87171",
            "--error": "#fca5a5",
            "--error-tint": "rgba(239, 68, 68, 0.15)",
            "--error-border": "rgba(239, 68, 68, 0.38)",
            "--danger-hover-bg": "rgba(153, 27, 27, 0.35)",
            "--danger-hover-text": "#fecaca",
        },
    ),
    ThemePreset(
        id="mint-city",
        name="Mint City",
        description="Dark Plum trim, Charcoal chassis, industrial Teal, and crisp Mint highlights",
        swatches={
            "Plum": "#1e1024",
            "Charcoal": "#102324",
            "Teal": "#14b8a6",
            "Mint": "#5eead4",
        },
        variables={
            "--bg-base": "#091212",
            "--bg-canvas": "#091212",
            "--bg-surface": "#102324",
            "--bg-card": "#17383a",
            "--bg-container-lowest": "#050a0a",
            "--bg-container-low": "#102324",
            "--bg-container": "#17383a",
            "--bg-container-high": "#1c4547",
            "--bg-container-highest": "#215356",
            "--bg-titlebar": "#1e1024",
            "--bg-menu": "#102324",
            "--bg-menu-hover": "#1c4547",
            "--bg-transport": "rgba(5, 10, 10, 0.95)",
            "--surface-tint-subtle": "rgba(94, 234, 212, 0.05)",
            "--border": "#215356",
            "--border-strong": "#215356",
            "--border-subtle": "#122d2f",
            "--border-divider": "#17383a",
            "--border-focus": "#14b8a6",
            "--text": "#f0fdfa",
            "--text-primary": "#f0fdfa",
            "--text-secondary": "#99f6e4",
            "--text-muted": "#5eead4",
            "--text-dim": "#4fd1c5",
            "--primary": "#14b8a6",
            "--primary-hover": "#0d9488",
            "--on-primary": "#041212",
            "--primary-glow": "rgba(20, 184, 166, 0.35)",
            "--primary-tint": "rgba(20, 184, 166, 0.15)",
            "--primary-border": "rgba(45, 212, 191, 0.35)",
            "--secondary": "#2dd4bf",
            "--secondary-glow": "rgba(45, 212, 191, 0.25)",
            "--secondary-tint": "rgba(45, 212, 191, 0.14)",
            "--secondary-border": "rgba(45, 212, 191, 0.35)",
            "--tertiary": "#22c55e",
            "--tertiary-glow": "rgba(34, 197, 94, 0.25)",
            "--tertiary-tint": "rgba(34, 197, 94, 0.14)",
            "--tertiary-border": "rgba(34, 197, 94, 0.35)",
            "--accent": "#2dd4bf",
            "--status-ok": "#22c55e",
            "--status-warn": "#f59e0b",
            "--status-err": "#f87171",
            "--error": "#fca5a5",
            "--error-tint": "rgba(239, 68, 68, 0.15)",
            "--error-border": "rgba(239, 68, 68, 0.38)",
            "--danger-hover-bg": "rgba(153, 27, 27, 0.35)",
            "--danger-hover-text": "#fecaca",
        },
    ),
    ThemePreset(
        id="slate-audiophile",
        name="Slate Audiophile",
        description="Classic high-contrast dark console with emerald status indicators",
        swatches={
            "Charcoal": "#0f1115",
            "Slate": "#181a20",
            "Emerald": "#10b981",
        },
        variables={
            "--bg-base": "#0f1115",
            "--bg-canvas": "#0f1115",
            "--bg-surface": "#181a20",
            "--bg-card": "#22252c",
            "--bg-container-lowest": "#0b0e14",
            "--bg-container-low": "#181a20",
            "--bg-container": "#22252c",
            "--bg-container-high": "#272a31",
            "--bg-container-highest": "#313540",
            "--bg-titlebar": "#0b0d11",
            "--bg-menu": "#181a20",
            "--bg-menu-hover": "#272a31",
            "--bg-transport": "rgba(11, 14, 20, 0.95)",
            "--surface-tint-subtle": "rgba(52, 211, 153, 0.05)",
            "--border": "#313540",
            "--border-strong": "#313540",
            "--border-subtle": "#1d2026",
            "--border-divider": "#262932",
            "--border-focus": "#10b981",
            "--text": "#f3f4f6",
            "--text-primary": "#f3f4f6",
            "--text-secondary": "#d1d5db",
            "--text-muted": "#9ca3af",
            "--text-dim": "#8b949e",
            "--primary": "#10b981",
            "--primary-hover": "#059669",
            "--on-primary": "#05110d",
            "--primary-glow": "rgba(16, 185, 129, 0.35)",
            "--primary-tint": "rgba(16, 185, 129, 0.14)",
            "--primary-border": "rgba(52, 211, 153, 0.35)",
            "--secondary": "#34d399",
            "--secondary-glow": "rgba(52, 211, 153, 0.25)",
            "--secondary-tint": "rgba(52, 211, 153, 0.14)",
            "--secondary-border": "rgba(52, 211, 153, 0.35)",
            "--tertiary": "#10b981",
            "--tertiary-glow": "rgba(16, 185, 129, 0.25)",
            "--tertiary-tint": "rgba(16, 185, 129, 0.14)",
            "--tertiary-border": "rgba(16, 185, 129, 0.35)",
            "--accent": "#34d399",
            "--status-ok": "#10b981",
            "--status-warn": "#f59e0b",
            "--status-err": "#f87171",
            "--error": "#fca5a5",
            "--error-tint": "rgba(239, 68, 68, 0.15)",
            "--error-border": "rgba(239, 68, 68, 0.38)",
            "--danger-hover-bg": "rgba(153, 27, 27, 0.35)",
            "--danger-hover-text": "#fecaca",
        },
    ),
]

_SWATCH_AND_ALIAS_MAP: dict[str, str] = {
    "slate-classic": "slate-audiophile",
    "navy": "god-of-ink",
    "slate": "god-of-ink",
    "periwinkle": "god-of-ink",
    "uncut-amethyst": "wine",
    "uncut amethyst": "wine",
    "purple": "obsidian",
    "lavender": "obsidian",
    "ocean": "swimming-with-the-whales",
    "cobalt": "swimming-with-the-whales",
    "blue": "swimming-with-the-whales",
    "plum": "mint-city",
    "charcoal": "mint-city",
    "teal": "mint-city",
    "mint": "mint-city",
}


def get_available_themes() -> list[ThemePreset]:
    """Retrieve all defined theme presets."""
    return THEME_PRESETS


def get_theme_by_id(theme_id: str) -> ThemePreset:
    """Retrieve theme preset by identifier or sub-palette swatch name, defaulting to 'god-of-ink'."""
    clean_id = theme_id.lower().strip()
    clean_id = _SWATCH_AND_ALIAS_MAP.get(clean_id, clean_id)
    for preset in THEME_PRESETS:
        if preset.id == clean_id:
            return preset
    return THEME_PRESETS[0]


def compute_relative_luminance(hex_color: str) -> float:
    """Compute WCAG 2.1 relative luminance for a 6-digit hex color (#RRGGBB)."""
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(c * 2 for c in cleaned)
    if len(cleaned) != 6:
        raise ValueError(f"Expected 6-digit hex color, got '{hex_color}'.")

    channels = [int(cleaned[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def compute_contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """Compute WCAG 2.1 contrast ratio between two hex colors (1.0 to 21.0)."""
    l1 = compute_relative_luminance(fg_hex)
    l2 = compute_relative_luminance(bg_hex)
    bright, dark = max(l1, l2), min(l1, l2)
    return round((bright + 0.05) / (dark + 0.05), 2)


def verify_theme_contrast(theme_id: str) -> dict[str, float]:
    """Calculate key WCAG contrast ratios for labels, buttons, menu bars, and status indicators."""
    theme = get_theme_by_id(theme_id)
    v = theme.variables
    return {
        "text_on_base": compute_contrast_ratio(v["--text-primary"], v["--bg-base"]),
        "text_on_surface": compute_contrast_ratio(v["--text-primary"], v["--bg-surface"]),
        "text_on_menu": compute_contrast_ratio(v["--text-primary"], v["--bg-menu"]),
        "muted_on_base": compute_contrast_ratio(v["--text-muted"], v["--bg-base"]),
        "muted_on_surface": compute_contrast_ratio(v["--text-muted"], v["--bg-surface"]),
        "dim_on_base": compute_contrast_ratio(v["--text-dim"], v["--bg-base"]),
        "button_on_primary": compute_contrast_ratio(v["--on-primary"], v["--primary"]),
        "status_ok_on_surface": compute_contrast_ratio(v["--status-ok"], v["--bg-surface"]),
        "status_warn_on_surface": compute_contrast_ratio(v["--status-warn"], v["--bg-surface"]),
        "status_err_on_surface": compute_contrast_ratio(v["--status-err"], v["--bg-surface"]),
    }


def get_theme_css_variables(theme_id: str = "god-of-ink") -> str:
    """Generate CSS variable declarations string for a target theme."""
    theme = get_theme_by_id(theme_id)
    declarations = [f"  {k}: {v};" for k, v in theme.variables.items()]
    return f":root[data-theme='{theme.id}'], html[data-theme='{theme.id}'], body[data-theme='{theme.id}'] {{\n" + "\n".join(declarations) + "\n}"


def generate_all_themes_css() -> str:
    """Generate complete CSS stylesheet declaring custom properties for all presets."""
    blocks = [get_theme_css_variables(preset.id) for preset in THEME_PRESETS]
    return "\n\n".join(blocks)
