"""Desktop top menu bar data models and action routing for vibeplay."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MenuItem:
    """Individual menu command item."""

    id: str
    label: str
    shortcut: str | None = None
    action_endpoint: str | None = None
    is_separator: bool = False
    is_checked: bool | None = None
    is_disabled: bool = False


@dataclass
class MenuSection:
    """Top-level menu section containing child items."""

    id: str
    label: str
    items: list[MenuItem] = field(default_factory=list)


def build_desktop_menu_bar() -> list[MenuSection]:
    """Build complete top menu bar hierarchy conforming to Desktop App Plan Phase 2 specifications.

    Returns:
        list[MenuSection]: Structured sections for File, Edit, Library, Playback, DSP, View, Help.
    """
    return [
        MenuSection(
            id="file",
            label="File",
            items=[
                MenuItem(
                    id="file_add_folder",
                    label="Add Music Folder...",
                    shortcut="Ctrl+O",
                    action_endpoint="/api/library/add-folder",
                ),
                MenuItem(
                    id="file_rescan",
                    label="Rescan Library",
                    shortcut="Ctrl+R",
                    action_endpoint="/api/library/rescan",
                ),
                MenuItem(id="file_sep_1", label="", is_separator=True),
                MenuItem(
                    id="file_settings",
                    label="Preferences & Hardware Settings...",
                    shortcut="Ctrl+,",
                    action_endpoint="#settings-popover",
                ),
                MenuItem(id="file_sep_2", label="", is_separator=True),
                MenuItem(
                    id="file_quit",
                    label="Quit vibeplay",
                    shortcut="Ctrl+Q",
                    action_endpoint="/api/app/quit",
                ),
            ],
        ),
        MenuSection(
            id="edit",
            label="Edit",
            items=[
                MenuItem(
                    id="edit_clear_queue",
                    label="Clear Playback Queue",
                    action_endpoint="/api/player/clear",
                ),
                MenuItem(id="edit_sep_1", label="", is_separator=True),
                MenuItem(
                    id="edit_cleanup_cache",
                    label="Clean Expired Caches (TTL > 30d)",
                    action_endpoint="/api/cache/cleanup",
                ),
                MenuItem(
                    id="edit_purge_cache",
                    label="Purge All Network & LLM Caches",
                    action_endpoint="/api/cache/purge",
                ),
            ],
        ),
        MenuSection(
            id="library",
            label="Library",
            items=[
                MenuItem(
                    id="lib_rescan",
                    label="Scan for New Audio Files",
                    shortcut="Ctrl+R",
                    action_endpoint="/api/library/rescan",
                ),
                MenuItem(
                    id="lib_analyze",
                    label="Run Essentia Feature Analyzer",
                    action_endpoint="/api/library/analyze",
                ),
                MenuItem(
                    id="lib_duplicates",
                    label="Scan for Lossless/Lossy Duplicates",
                    action_endpoint="/api/library/duplicates",
                ),
                MenuItem(
                    id="lib_clusters",
                    label="Generate HDBSCAN Vibe Clusters",
                    action_endpoint="/api/library/clusters",
                ),
            ],
        ),
        MenuSection(
            id="playback",
            label="Playback",
            items=[
                MenuItem(
                    id="play_toggle",
                    label="Play / Pause",
                    shortcut="Space",
                    action_endpoint="/api/player/toggle",
                ),
                MenuItem(
                    id="play_next",
                    label="Next Track",
                    shortcut="Ctrl+Right",
                    action_endpoint="/api/player/next",
                ),
                MenuItem(
                    id="play_prev",
                    label="Previous Track",
                    shortcut="Ctrl+Left",
                    action_endpoint="/api/player/prev",
                ),
                MenuItem(id="play_sep_1", label="", is_separator=True),
                MenuItem(
                    id="play_vol_up",
                    label="Increase Volume (+5%)",
                    shortcut="Ctrl+Up",
                    action_endpoint="/api/player/volume-step?delta=5",
                ),
                MenuItem(
                    id="play_vol_down",
                    label="Decrease Volume (-5%)",
                    shortcut="Ctrl+Down",
                    action_endpoint="/api/player/volume-step?delta=-5",
                ),
                MenuItem(
                    id="play_mute",
                    label="Mute / Unmute",
                    shortcut="Ctrl+M",
                    action_endpoint="/api/player/mute-toggle",
                ),
            ],
        ),
        MenuSection(
            id="dsp",
            label="DSP",
            items=[
                MenuItem(
                    id="dsp_bitperfect",
                    label="Pure Bit-Perfect (Direct ALSA hw:)",
                    action_endpoint="/api/dsp/profile?profile=pure-bitperfect",
                ),
                MenuItem(
                    id="dsp_spatial",
                    label="7.1.4 Spatial Headphones (SOFA 3D + PEQ)",
                    action_endpoint="/api/dsp/profile?profile=spatial-headphones",
                ),
                MenuItem(
                    id="dsp_passthrough",
                    label="AV Receiver Passthrough (HDMI Bitstream)",
                    action_endpoint="/api/dsp/profile?profile=receiver-passthrough",
                ),
                MenuItem(id="dsp_sep_1", label="", is_separator=True),
                MenuItem(
                    id="dsp_toggle_spatial",
                    label="Toggle 3D Binaural Virtualization",
                    action_endpoint="/api/dsp/spatial/toggle",
                ),
                MenuItem(
                    id="dsp_latency",
                    label="Inspect Kernel Latency & Xruns...",
                    action_endpoint="/api/dsp/latency",
                ),
            ],
        ),
        MenuSection(
            id="view",
            label="View",
            items=[
                MenuItem(
                    id="view_fullscreen",
                    label="Toggle Fullscreen",
                    shortcut="F11",
                    action_endpoint="window.toggle_fullscreen()",
                ),
                MenuItem(
                    id="view_reload",
                    label="Reload View",
                    shortcut="F5",
                    action_endpoint="window.location.reload()",
                ),
            ],
        ),
        MenuSection(
            id="help",
            label="Help",
            items=[
                MenuItem(
                    id="help_shortcuts",
                    label="Keyboard Shortcuts",
                    action_endpoint="#modal-shortcuts",
                ),
                MenuItem(
                    id="help_diagnostics",
                    label="Audio Hardware Audit...",
                    action_endpoint="#modal-hardware-audit",
                ),
                MenuItem(
                    id="help_about",
                    label="About vibeplay",
                    action_endpoint="#modal-about",
                ),
            ],
        ),
    ]
