# Desktop Installation and Integration Scripts

This directory contains integration scripts for deploying `vibeplay` natively on Ubuntu systems conforming to FreeDesktop and systemd standards.

---

## Script Manifest
- `build-deb.sh`: Assembles a standalone Debian `.deb` package (`dist/vibeplay_0.1.0_amd64.deb`) including binary, launcher, scalable icons, systemd user service, and postinst desktop/icon cache triggers.
- `install-desktop.sh`: Installs the compiled binary to `~/.local/bin/`, copies application icon assets to `~/.local/share/icons/hicolor/`, registers `vibeplay.desktop` into `~/.local/share/applications/`, and updates the desktop database.
- `vibeplay.service`: User systemd unit template for headless background library scanning and audio service management (`~/.config/systemd/user/vibeplay.service`).
