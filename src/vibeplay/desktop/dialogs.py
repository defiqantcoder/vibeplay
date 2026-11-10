"""Native desktop dialogs for selecting files and directories."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _find_existing_dir_from_roots(raw_dir: Path | str, roots: list[Path]) -> str | None:
    """Locate an existing directory matching ``raw_dir`` by traversing ``roots`` via directory listings."""
    from vibeplay.desktop.security import resolve_within

    try:
        resolved_target = resolve_within(raw_dir, roots)
    except (PermissionError, ValueError):
        logger.warning("Ignoring initial_dir outside permitted directories.")
        return None

    for root in roots:
        base_dir = Path(root).resolve()
        try:
            rel_parts = resolved_target.relative_to(base_dir).parts
        except ValueError:
            continue
        cur = base_dir
        if not cur.is_dir():
            continue
        found = True
        for part in rel_parts:
            try:
                match = next((entry for entry in cur.iterdir() if entry.name == part and entry.is_dir()), None)
            except OSError:
                match = None
            if match is None:
                found = False
                break
            cur = match
        if found:
            return str(cur)
    return None


def choose_directory_dialog(
    title: str = "Select Music Library Folder",
    initial_dir: Path | str | None = None,
) -> str | None:
    """Open a native OS folder chooser dialog and return the selected directory path.

    Tries system dialog tools in order:
    1. zenity (native GTK/GNOME file chooser)
    2. kdialog (KDE/Qt file chooser)
    3. PyGObject Gtk.FileChooserNative
    4. None (if cancelled or headless)

    Args:
        title: Window title for the dialog.
        initial_dir: Optional starting directory path.

    Returns:
        str | None: Selected folder path, or None if user cancelled or dialog unavailable.
    """
    from vibeplay.desktop.security import allowed_media_roots

    roots = allowed_media_roots()
    if initial_dir:
        initial_dir = _find_existing_dir_from_roots(initial_dir, roots)
    title = str(title).replace("\x00", "")

    # 1. Check for zenity
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", f"--title={title}"]
        if initial_dir and Path(initial_dir).is_dir():
            cmd.append(f"--filename={Path(initial_dir).resolve()}/")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode == 0:
                selected = res.stdout.strip()
                if selected:
                    p = Path(selected).resolve()
                    if p.is_dir():
                        return str(p)
            elif res.returncode == 1:
                # User pressed Cancel
                return None
        except Exception as err:
            logger.debug("Zenity folder dialog failed: %s", err)

    # 2. Check for kdialog
    if shutil.which("kdialog"):
        start = str(Path(initial_dir).resolve()) if initial_dir else str(Path.home())
        cmd = ["kdialog", "--getexistingdirectory", start, f"--title={title}"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode == 0:
                selected = res.stdout.strip()
                if selected:
                    p = Path(selected).resolve()
                    if p.is_dir():
                        return str(p)
            elif res.returncode == 1:
                return None
        except Exception as err:
            logger.debug("Kdialog folder dialog failed: %s", err)

    # 3. Check for PyGObject Gtk.FileChooserNative
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk

            dialog = Gtk.FileChooserNative.new(
                title,
                None,
                Gtk.FileChooserAction.SELECT_FOLDER,
                "_Select",
                "_Cancel",
            )
            if initial_dir and Path(initial_dir).is_dir():
                dialog.set_current_folder(str(Path(initial_dir).resolve()))

            response = dialog.run()
            chosen_path = None
            if response == Gtk.ResponseType.ACCEPT:
                chosen_path = dialog.get_filename()
            dialog.destroy()
            if chosen_path:
                p = Path(chosen_path).resolve()
                if p.is_dir():
                    return str(p)
        except Exception as err:
            logger.debug("GTK native folder chooser failed: %s", err)

    return None
