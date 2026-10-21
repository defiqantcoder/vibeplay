# vibeplay

Local-first music library scanner, metadata enricher, audio feature analyzer, and vibe-based smart playlist generator for Ubuntu 24.04.

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

## Installation & Setup

### 1. Prerequisites (Ubuntu 24.04)

Ensure Python 3.12 and `uv` are installed:

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh
```

*(Optional)* Install `fpcalc` for acoustic fingerprinting:
```bash
sudo apt update && sudo apt install -y libchromaprint-tools
```

### 2. Configure Environment

Copy the example environment file:
```bash
cp .env.example .env
```

Optionally set your `ACOUSTID_API_KEY` or `GEMINI_API_KEY` inside `.env`. Secrets are always read from environment variables or `.env` and never hardcoded.

### 3. Install Dependencies

Sync virtual environment and project dependencies using `uv`:
```bash
uv sync
```

---

## Usage

All commands are accessible via the `vibeplay` CLI runner:

### Show Help and Available Commands
```bash
uv run vibeplay --help
```

Expected output:
```text
 Usage: vibeplay [OPTIONS] COMMAND [ARGS]...

 Local music library scanner, metadata enricher, and vibe-based smart playlist
 generator.

╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ scan      Scan music directory recursively, index audio files, and extract   │
│           tags.                                                              │
│ enrich    Fingerprint audio tracks and query MusicBrainz for canonical       │
│           metadata.                                                          │
│ analyze   Analyze audio files to extract acoustic features, rhythm, and      │
│           embeddings.                                                        │
│ clusters  Compute normalized vibe vectors and generate track clusters.       │
│ playlist  Generate a smart playlist based on seed track, target vibe, or     │
│           arc.                                                               │
│ export    Export a saved playlist to an M3U, M3U8, JSON, or CSV file.        │
│ serve     Launch the local FastAPI web server and user interface.            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### Run CLI Commands
During Phase 1 (scaffolding), CLI subcommands output `not implemented`:
```bash
uv run vibeplay scan /path/to/music
uv run vibeplay enrich
uv run vibeplay analyze
uv run vibeplay clusters
uv run vibeplay playlist --name "Late Night"
uv run vibeplay export 1 --format m3u8
uv run vibeplay serve
```

---

## Running Tests

Run the test suite via pytest:
```bash
uv run pytest
```

Expected output:
```text
============================= test session starts ==============================
collected 4 items

tests/test_smoke.py ....                                                 [100%]

============================== 4 passed in 0.13s ===============================
```

---

## Documentation

See [SPEC.md](SPEC.md) for full architectural design, SQLite schema details, module definitions, and the multi-phase implementation roadmap.
