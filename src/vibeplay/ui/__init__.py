"""UI components, menu bar hierarchy, and theme engine for the vibeplay desktop console."""

from __future__ import annotations

from vibeplay.ui.menu import MenuItem, MenuSection, build_desktop_menu_bar
from vibeplay.ui.theme import (
    THEME_PRESETS,
    ThemePreset,
    generate_all_themes_css,
    get_available_themes,
    get_theme_by_id,
    get_theme_css_variables,
)

__all__ = [
    "MenuItem",
    "MenuSection",
    "THEME_PRESETS",
    "ThemePreset",
    "build_desktop_menu_bar",
    "generate_all_themes_css",
    "get_available_themes",
    "get_theme_by_id",
    "get_theme_css_variables",
]
