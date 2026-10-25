# vibeplay

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Platform: Ubuntu 24.04](https://img.shields.io/badge/platform-Ubuntu%2024.04-orange.svg)
![Tests: 305 passing](https://img.shields.io/badge/tests-305%20passing-brightgreen.svg)

Local-first music library scanner, metadata enricher, audio feature analyzer, and vibe-based smart playlist generator for Ubuntu 24.04.

## High-Level Overview

VibePlay is an advanced local music library manager designed for audiophiles and music enthusiasts who demand uncompromising quality and intelligent organization.

*   **Bit-Perfect ALSA Audiophile Engine:** Ensures your audio is delivered directly to your DAC without unwanted resampling or processing, preserving the original fidelity.
*   **Essentia Acoustic Vector Engine:** Analyzes your tracks to extract deep acoustic features (rhythm, tonality, texture) using state-of-the-art machine learning.
*   **SOFA 7.1.4 HRTF Spatial Convolver:** Provides an immersive spatial audio experience using head-related transfer functions.
*   **Interactive 4-step Playlist Builder:** Create perfect playlists based on mood, energy arcs, or specific seed tracks.

## Core Principles

- **Strictly Read-Only:** vibeplay **NEVER** modifies, moves, renames, retags, or deletes your audio files. Your music collection remains untouched.
- **Local-First & Private:** Analysis metrics, acoustic features, and generated playlists reside strictly in your local SQLite database. No audio files or raw audio waveforms are uploaded to the cloud.
- **Incremental & Fast:** Uses file sizes, modification timestamps (`mtime`), and hashes to avoid redundant work across scans.

---

## Tech Stack

- **Runtime & Packaging:** Python 3.12, managed with [uv](https://docs.astral.sh/uv/)
- **Database:** SQLite via Python standard library `sqlite3` (WAL mode enabled)
- **Tag Extraction:** [mutagen](https://mutagen.readthedocs.io/)
- **Fingerprinting & Enrichment:** [pyacoustid](https://github.com/beetbox/pyacoustid) (Chromaprint/fpcalc), [musicbrainzngs](https://python-musicbrainzngs.readthedocs.io/)
- **Audio Analysis:** [Essentia](https://essentia.upf.edu/) (primary extractor) with [librosa](https://librosa.org/) (fallback)
- **Vibe Modeling & Clustering:** [scikit-learn](https://scikit-learn.org/)
- **Configuration & Validation:** [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- **Command-Line Interface:** [Typer](https://typer.tiangolo.com/)
- **Testing:** [pytest](https://docs.pytest.org/)

---

## Architecture Summary & Directory Layout

The project follows a modular structure separated by distinct phases:

*   `src/vibeplay/`: Core application package.
    *   `api/`: FastAPI backend routes.
    *   `cli/`: Typer command-line interface.
    *   `core/`: Core business logic, configuration, and data models.
    *   `db/`: SQLite database interactions.
    *   `dsp/`: Audio routing, DSP, and hardware receiver management.
    *   `templates/`: HTML templates for the web UI.
    *   `ui/`: Web interface modules.
*   `tests/`: Comprehensive test suite.
*   `packaging/`: Configuration for PyInstaller and Debian package creation.
*   `scripts/`: Utility scripts.

---

## Installation & Quick Start

VibePlay can be installed either via a pre-built Debian package or from source.

### Option 1: Debian Package (Recommended for Users)

If you have built or downloaded the `.deb` package:

```bash
sudo apt install ./dist/vibeplay_0.1.0_amd64.deb
```
*This installs the application and necessary system dependencies (ffmpeg, libsndfile1).*

### Option 2: Source Setup via `uv` (For Development)

#### 1. Prerequisites (Ubuntu 24.04)

Ensure Python 3.12 and `uv` are installed:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh > install.sh && chmod +x install.sh && ./install.sh
```

Install `ffmpeg` and `libsndfile1` (required for audio processing) and optionally `fpcalc` for acoustic fingerprinting:
```bash
sudo apt update && sudo apt install -y ffmpeg libsndfile1 libchromaprint-tools
```

#### 2. Configure Environment

Copy the example environment file:
```bash
cp .env.example .env
```

Optionally set your `ACOUSTID_API_KEY` or `GEMINI_API_KEY` inside `.env`. Secrets are always read from environment variables or `.env` and never hardcoded.

#### 3. Install Dependencies

Sync virtual environment and project dependencies using `uv`:
```bash
uv sync
```

---

## Keybindings Reference

| Shortcut       | Action                                  |
| :------------- | :-------------------------------------- |
| `Ctrl+R`       | Refresh library view                    |
| `Ctrl+O`       | Open file / directory                   |
| `Ctrl+,`       | Open Settings                           |
| `Space` / `F10`| Play / Pause                            |
| `F9` / `F11`   | Volume Down / Up                        |
| `F5` / `F6` / `F7`| Previous / Play-Pause / Next (Media) |
| `F12`          | Open Developer Tools                    |

---

## Usage Walkthrough

All commands are accessible via the `vibeplay` CLI runner:

### Show Help and Available Commands
```bash
uv run vibeplay --help
```

### 1. Scan your library
Scan your music directory recursively, index audio files, and extract tags into the local SQLite database.
```bash
uv run vibeplay scan /path/to/your/music
```

### 2. Enrich Metadata (Optional)
Fingerprint audio tracks and query MusicBrainz for canonical metadata.
```bash
uv run vibeplay enrich
```

### 3. Analyze Audio
Analyze audio files to extract acoustic features, rhythm, and embeddings. This requires `ffmpeg` and `libsndfile1` to be installed.
```bash
uv run vibeplay analyze
```

### 4. Create Vibe Clusters
Compute normalized vibe vectors and generate track clusters based on the analyzed features.
```bash
uv run vibeplay clusters
```

### 5. Generate Playlists
Generate a smart playlist based on seed track, target vibe, or arc.
```bash
uv run vibeplay playlist --name "Chill Evening" --vibe chill
uv run vibeplay playlist --name "Workout" --arc peak
```

### 6. Export Playlists
Export a saved playlist to an M3U, M3U8, JSON, or CSV file.
```bash
uv run vibeplay export 1 --format m3u8
```

### 7. Find Duplicates
Find likely duplicate tracks in the library based on MusicBrainz ID or acoustic features.
```bash
uv run vibeplay duplicates
```

### 8. Web Interface
Launch the local FastAPI web server and user interface.
```bash
uv run vibeplay serve
```

---

## CI / CD Workflow

This project includes a GitHub Actions workflow (`.github/workflows/ci.yml`) that runs automatically on push and pull requests to the `main` branch. It performs the following steps on an `ubuntu-24.04` runner:
1.  Sets up Python 3.12.
2.  Installs `uv`, `ffmpeg`, and `libsndfile1`.
3.  Syncs project dependencies using `uv`.
4.  Lints and checks formatting using `ruff`.
5.  Runs the test suite and generates a coverage report using `pytest-cov`.

---

## Automation & Scheduling

You can automate the scanning, enrichment, and analysis of your library using a simple shell script and a cron job or systemd timer.

### Example Automation Script (`auto_vibeplay.sh`)

```bash
#!/bin/bash
# auto_vibeplay.sh

MUSIC_DIR="/path/to/your/music"
cd /path/to/vibeplay

# 1. Scan for new/changed files
uv run vibeplay scan "$MUSIC_DIR"

# 2. Enrich new tracks
uv run vibeplay enrich

# 3. Analyze audio features
uv run vibeplay analyze

# 4. Update clusters
uv run vibeplay clusters
```

Make the script executable:
```bash
chmod +x auto_vibeplay.sh
```

### Systemd User Service for Web UI (`vibeplay.service`)

You can run the `vibeplay serve` web UI as a background service. Create `~/.config/systemd/user/vibeplay.service`:

```ini
[Unit]
Description=Vibeplay Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/vibeplay
ExecStart=/home/youruser/.cargo/bin/uv run vibeplay serve
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Enable and start the service:
```bash
systemctl --user enable vibeplay.service
systemctl --user start vibeplay.service
```

---

## Troubleshooting

-   **`FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`**:
    -   **Cause**: `ffmpeg` is not installed or not in your system's PATH. It is required for the audio analysis phase.
    -   **Solution**: Run `sudo apt-get install ffmpeg` (Ubuntu/Debian) or install via your system's package manager.
-   **`mutagen could not recognize audio format`**:
    -   **Cause**: The file might be corrupted, have an unsupported extension, or lack valid metadata headers.
    -   **Solution**: Ensure the file plays correctly in a standard media player. If the file is valid but unsupported, `vibeplay` will safely log an error and skip it during scanning.
-   **`ModuleNotFoundError` when running commands**:
    -   **Cause**: Virtual environment is not synced.
    -   **Solution**: Run `uv sync` to ensure all dependencies are installed. Ensure you are using `uv run` to execute commands within the virtual environment context.
-   **Slow analysis process**:
    -   **Cause**: Audio analysis is computationally intensive.
    -   **Solution**: `vibeplay` uses incremental scanning and analysis. Only new or modified files will be processed on subsequent runs. Be patient during the initial `analyze` run.
-   **No clusters generated**:
    -   **Cause**: You must run `vibeplay analyze` before running `vibeplay clusters`.

---

## Running Tests

Run the test suite via pytest:
```bash
uv run pytest
```

Generate a coverage report:
```bash
uv run pytest --cov=src/vibeplay --cov-report=term-missing
```

---

## Documentation

See [SPEC.md](SPEC.md) for full architectural design, SQLite schema details, module definitions, and the multi-phase implementation roadmap.
