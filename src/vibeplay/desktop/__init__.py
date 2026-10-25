"""Desktop application shell, window management, and supervisor subsystem for vibeplay."""

from __future__ import annotations

from vibeplay.desktop.constants import (
    DEFAULT_BACKEND_HOST,
    DEFAULT_BACKEND_PORT,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_MIN_HEIGHT,
    DEFAULT_WINDOW_MIN_WIDTH,
    DEFAULT_WINDOW_WIDTH,
    WINDOW_TITLE,
)
from vibeplay.desktop.dialogs import choose_directory_dialog
from vibeplay.desktop.environment import (
    DesktopEnvironment,
    find_free_loopback_port,
    generate_ephemeral_session_token,
    inspect_desktop_environment,
)
from vibeplay.desktop.notifications import TrackNotificationDispatcher
from vibeplay.desktop.packaging import (
    BUNDLE_DATAS,
    BUNDLE_ENTRYPOINT,
    BUNDLE_EXCLUDES,
    BUNDLE_HIDDEN_IMPORTS,
    BUNDLE_NAME,
    BundleAssetReport,
    collect_pyinstaller_datas,
    get_bundle_root,
    is_frozen_bundle,
    resolve_dsp_profiles_dir,
    resolve_models_dir,
    resolve_package_resource,
    resolve_static_dir,
    resolve_templates_dir,
    verify_bundle_assets,
)
from vibeplay.desktop.release_gate import (
    GateCheckResult,
    ReleaseGateReport,
    run_release_gate_checks,
)
from vibeplay.desktop.security import is_loopback_host, validate_loopback_host
from vibeplay.desktop.settings import (
    DEFAULT_DESKTOP_SETTINGS_PATH,
    DesktopSettings,
    load_desktop_settings,
    save_desktop_settings,
    update_desktop_settings,
)
from vibeplay.desktop.supervisor import (
    DEFAULT_MPD_DATA_DIR,
    DesktopSupervisor,
    generate_audiophile_mpd_config,
    run_desktop,
)

__all__ = [
    "BUNDLE_DATAS",
    "BUNDLE_ENTRYPOINT",
    "BUNDLE_EXCLUDES",
    "BUNDLE_HIDDEN_IMPORTS",
    "BUNDLE_NAME",
    "BundleAssetReport",
    "DEFAULT_BACKEND_HOST",
    "DEFAULT_BACKEND_PORT",
    "DEFAULT_DESKTOP_SETTINGS_PATH",
    "DEFAULT_MPD_DATA_DIR",
    "DEFAULT_WINDOW_HEIGHT",
    "DEFAULT_WINDOW_MIN_HEIGHT",
    "DEFAULT_WINDOW_MIN_WIDTH",
    "DEFAULT_WINDOW_WIDTH",
    "DesktopEnvironment",
    "DesktopSettings",
    "DesktopSupervisor",
    "GateCheckResult",
    "ReleaseGateReport",
    "TrackNotificationDispatcher",
    "WINDOW_TITLE",
    "choose_directory_dialog",
    "collect_pyinstaller_datas",
    "find_free_loopback_port",
    "generate_audiophile_mpd_config",
    "generate_ephemeral_session_token",
    "get_bundle_root",
    "inspect_desktop_environment",
    "is_frozen_bundle",
    "load_desktop_settings",
    "resolve_dsp_profiles_dir",
    "resolve_models_dir",
    "resolve_package_resource",
    "resolve_static_dir",
    "resolve_templates_dir",
    "run_desktop",
    "run_release_gate_checks",
    "save_desktop_settings",
    "update_desktop_settings",
    "validate_loopback_host",
    "is_loopback_host",
    "verify_bundle_assets",
]
