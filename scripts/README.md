# Desktop Installation and Integration Scripts

This directory contains integration scripts for deploying `vibeplay` natively on Ubuntu systems conforming to FreeDesktop and systemd standards.

---

## Script Manifest
- `install-desktop.sh`: Installs the compiled binary to `~/.local/bin/`, copies application icon assets to `~/.local/share/icons/hicolor/`, registers `vibeplay.desktop` into `~/.local/share/applications/`, and updates the desktop database.
- `vibeplay.service`: User systemd unit template for headless background library scanning and audio service management (`~/.config/systemd/user/vibeplay.service`).
