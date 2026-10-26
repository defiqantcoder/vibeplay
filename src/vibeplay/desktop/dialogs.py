"""Native desktop dialogs for selecting files and directories."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


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
    # 1. Check for zenity
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", f"--title={title}"]
        if initial_dir and Path(initial_dir).is_dir():
            cmd.append(f"--filename={Path(initial_dir).resolve()}/")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode == 0:
                selected = res.stdout.strip()
                if selected and Path(selected).is_dir():
                    return selected
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
                if selected and Path(selected).is_dir():
                    return selected
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
            if chosen_path and Path(chosen_path).is_dir():
                return chosen_path
        except Exception as err:
            logger.debug("GTK native folder chooser failed: %s", err)

    return None
