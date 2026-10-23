# Packaging Architecture for vibeplay (Ubuntu 24.04 LTS)

This directory contains specifications and assets for building a standalone, self-contained desktop binary and system package on **Ubuntu 24.04 LTS (Noble Numbat)**.

---

## 1. Runtime Stack & Target Environment
- **OS**: Ubuntu 24.04 LTS (x86_64)
- **Desktop Environments**: Cinnamon, GNOME, XFCE (Wayland & X11)
- **GUI Engine**: PyWebView 6.x using native GTK3 (`gi.repository.Gtk`) and WebKit2GTK 4.1 (`gi.repository.WebKit2`)
- **Python**: 3.12+ (CPython)
- **Bundler**: PyInstaller 6.x

---

## 2. Bundled Components
When building `vibeplay.spec`:
- **Core Package**: `vibeplay` and `vibe_dsp` source packages.
- **Templates & Static Assets**:
  - `src/vibeplay/templates/` (`*.html`, Jinja2 templates)
  - `src/vibeplay/static/` (`*.css`, `*.js`, icons)
- **Audio Models & Weights**:
  - Essentia feature extractor models and mood classification weights.
- **DSP Configuration Templates**:
  - Default SOFA HRTF impulse models (`~/.local/share/vibe-dsp/hrtf/`).
  - PEQ reference curves (`src/vibe_dsp/profiles/*.txt`).

---

## 3. Package Distribution Formats

### A. Debian / Ubuntu Package (`.deb`)
Native `.deb` package built using `dpkg-deb`:
- Built via `scripts/build-deb.sh`
- Output: `dist/vibeplay_0.1.0_amd64.deb`
- Installs to `/usr/bin/vibeplay-desktop`, `/usr/share/applications/vibeplay.desktop`, `/usr/share/icons/hicolor/scalable/apps/vibeplay.svg`, and `/usr/lib/systemd/user/vibeplay.service`.
- Dependencies: `libc6`, `libwebkit2gtk-4.1-0`, `mpd`, `libasound2`, `libnotify-bin`.
- Installation:
  ```bash
  sudo apt install ./dist/vibeplay_0.1.0_amd64.deb
  # or
  sudo dpkg -i dist/vibeplay_0.1.0_amd64.deb
  ```

### B. Flatpak Manifest
- Specification: `packaging/flatpak/com.vibeplay.VibePlay.yaml`
- Target runtime: `org.gnome.Platform//46`
- Sandboxed hardware access: `--device=all` (ALSA), `--socket=pulseaudio`, `--socket=wayland`, `--socket=x11`, `--filesystem=xdg-music:ro`.

---

## 4. Exclusions
To optimize binary size and security:
- Testing tools: `pytest`, `pytest-cov`.
- Build tooling: `uv_build`, `wheel`, `pip`.
- Unused Qt/Tk GUI backends.
