# vibeplay — Specification & Architecture Design

## 1. Goals and Non-Goals

### 1.1 Goals
- **Local-First & Private:** vibeplay runs entirely on local hardware (Ubuntu 24.04). Audio files, derived features, and smart playlists remain on the local machine.
- **Strict Read-Only Guarantee:** The user's audio library directory is treated as strictly read-only. vibeplay will never create, modify, rename, move, retag, or delete audio files on disk. All discovered tags, acoustic fingerprints, audio analysis metrics, and playlists reside solely in a separate SQLite database.
- **Fast, Incremental Library Scanning:** Efficiently traverse large music libraries, extract embedded tags (ID3, Vorbis, FLAC, MP4) via `mutagen`, and track files using path, file size, modification timestamp (`mtime`), and content hashing to skip unchanged files on subsequent runs.
- **Metadata Enrichment:** Resolve incomplete tags by calculating acoustic fingerprints via Chromaprint/AcoustID (`pyacoustid`) and querying MusicBrainz (`musicbrainzngs`) under strict rate-limiting rules.
- **Deep Audio Analysis:** Extract acoustic descriptors including tempo (BPM), key, scale, integrated loudness, danceability, energy, mood metrics, and vector embeddings using Essentia (with librosa as a graceful fallback).
- **Vibe Vectors & Clustering:** Assemble multi-dimensional feature vectors, normalize them, and apply `scikit-learn` algorithms for clustering (e.g., K-Means, HDBSCAN) and nearest-neighbor similarity search.
- **Intelligent Playlist Engine:** Build playlists based on seed tracks, target vibe profiles, smooth transition arcs (e.g. warm-up to peak to cool-down), and artist/genre diversity constraints.
- **Universal Playlist Exporters:** Export generated playlists to standard formats such as `.m3u` / `.m3u8` and structured JSON.
- **Dual Interface:** Deliver an efficient Typer CLI for scripting and headless execution, complemented by a local FastAPI web server and lightweight browser UI for interactive exploration and visual cluster navigation.
- **Optional LLM Layer:** Support natural language playlist generation queries (e.g., "rainy afternoon jazz and lo-fi beats with low energy") by interpreting prompts against extracted vibe features, backed by an LLM response cache.

### 1.2 Non-Goals
- **No In-Place File Tagging or Modification:** No writing ID3 or Vorbis tags back to source media files.
- **No Cloud Audio Upload:** Audio waveforms, spectral data, or audio files are never uploaded to remote servers or third-party APIs.
- **No Full-Fledged Streaming Platform:** vibeplay is not an internet radio or streaming service clone; it is a local music library enrichment and playlist curation tool.
- **No Destructive Re-indexing:** Scans are incremental; existing analysis data is preserved across library refreshes.

---

## 2. Architecture Overview

vibeplay is organized as a sequential, multi-stage pipeline where each stage has clear input/output boundaries mediated by a central SQLite database.

```
+-------------+      +--------------+      +----------------+
| Audio Files | ---> |   Scanner    | ---> | SQLite: tracks |
+-------------+      +--------------+      +----------------+
                            |                       |
                            v                       v
                     +--------------+      +--------------------+
                     |  Enrichment  | ---> | SQLite: enrichment |
                     | (AcoustID /  |      +--------------------+
                     | MusicBrainz) |               |
                     +--------------+               v
                            |              +--------------------+
                            v              |   Audio Analysis   |
                     +--------------+ ---> | (Essentia/librosa) |
                     | Vibe Vectors |      +--------------------+
                     | & Clustering |               |
                     +--------------+               v
                            |              +--------------------+
                            v              |  SQLite: features  |
                     +-----------------+   +--------------------+
                     | Playlist Engine |            |
                     +-----------------+            v
                       |             |     +--------------------+
                       v             v     | SQLite: playlists  |
                 +-----------+  +--------+ +--------------------+
                 | Exporters |  | CLI /  |
                 | (M3U/JSON)|  | Web UI |
                 +-----------+  +--------+
```

### Stage Pipeline Details:
1. **Scanner (`vibeplay.scanner`):**
   - Recursively walks target directories using `pathlib.Path`.
   - Filters recognized audio formats (`.mp3`, `.flac`, `.ogg`, `.m4a`, `.opus`, `.wav`, `.wma`).
   - Checks `mtime` and `size` against the database; hashes new or modified files.
   - Extracts embedded metadata tags (title, artist, album, date, genre, track number) using `mutagen`.
   - Populates or updates the `tracks` table.
2. **Enrichment (`vibeplay.enrichment`):**
   - Identifies tracks lacking canonical metadata or MusicBrainz identifiers.
   - Generates Chromaprint fingerprints using `pyacoustid` (calling external `fpcalc`).
   - Queries the AcoustID web API to obtain MusicBrainz recording IDs.
   - Queries MusicBrainz via `musicbrainzngs` (adhering to rate-limiting policies: max 1 request/sec).
   - Stores retrieved identifiers and canonical metadata in the `enrichment` table.
3. **Audio Analysis (`vibeplay.analysis`):**
   - Decodes audio in read-only mode.
   - Primary analyzer: **Essentia** algorithms (e.g. `RhythmExtractor2013`, `KeyExtractor`, `LoudnessEBUR128`, `Danceability`, `MusicExtractor`, and high-level mood/genre models).
   - Fallback analyzer: **librosa** (tempo, beat tracking, chroma STFT, spectral centroid, RMS energy, MFCCs).
   - Serializes high-dimensional embeddings as raw binary BLOBs and records scalar metrics into the `features` table.
4. **Vibe Vectors & Clustering (`vibeplay.vectors`):**
   - Extracts scalar features (BPM, key/scale, energy, danceability, loudness, mood scores) and embeddings.
   - Standardizes and scales continuous variables using `scikit-learn` (`StandardScaler`, `MinMaxScaler`).
   - Constructs unified "vibe vectors" for each analyzed track.
   - Computes cluster assignments using K-Means or HDBSCAN.
   - Performs dimensionality reduction (PCA / UMAP / t-SNE) for 2D/3D visualization in the web UI.
5. **Playlist Engine (`vibeplay.playlist`):**
   - Accepts seed tracks, target vibe profiles, or natural language criteria.
   - Computes cosine or Euclidean nearest neighbors in vibe vector space.
   - Applies trajectory arcs (e.g. linear rise in energy, sinusoidal BPM transitions).
   - Enforces diversity rules (e.g. max 2 tracks per artist, minimum 15-minute gap between same-album songs).
   - Records created playlists into `playlists` and `playlist_tracks` tables.
6. **Exporters (`vibeplay.exporter`):**
   - Exports playlists to universal `.m3u` / `.m3u8` playlists with `#EXTINF` directives.
   - Supports export to JSON and CSV formats for external player integration.
7. **Interfaces (`vibeplay.cli` & `vibeplay.web`):**
   - Typer CLI for automation, scripted batch analysis, and headless environments.
   - FastAPI backend serving REST endpoints and lightweight frontend for visual cluster mapping and playlist generation.
8. **Optional LLM Layer (`vibeplay.llm`):**
   - Translates natural language descriptions into parametric vibe constraints and target vectors.
   - Caches queries and responses in `llm_cache` to minimize token usage and latency.

---

## 3. SQLite Database Schema

The database resides locally (default: `~/.local/share/vibeplay/vibeplay.db` or configured via `VIBEPLAY_DB_PATH`). SQLite foreign key enforcement (`PRAGMA foreign_keys = ON;`) and WAL mode (`PRAGMA journal_mode = WAL;`) are enabled.

```sql
-- Core tracks table: physical file information and embedded tags
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    hash TEXT NOT NULL,
    duration REAL,
    tags TEXT, -- JSON dictionary of raw extracted tags (artist, title, album, etc.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tracks_path ON tracks(path);
CREATE INDEX IF NOT EXISTS idx_tracks_hash ON tracks(hash);
CREATE INDEX IF NOT EXISTS idx_tracks_mtime ON tracks(mtime);

-- Metadata enrichment table: MusicBrainz and external identifiers
CREATE TABLE IF NOT EXISTS enrichment (
    track_id INTEGER PRIMARY KEY,
    mb_recording_id TEXT,
    mb_release_id TEXT,
    mb_artist_id TEXT,
    source TEXT NOT NULL, -- 'acoustid', 'musicbrainz', 'tags', etc.
    raw_metadata TEXT,    -- JSON payload returned by enrichment provider
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_enrichment_mb_recording ON enrichment(mb_recording_id);

-- Audio features table: acoustic analysis results and embedding vectors
CREATE TABLE IF NOT EXISTS features (
    track_id INTEGER PRIMARY KEY,
    analyzer_version TEXT NOT NULL, -- e.g. 'essentia-2.1b6', 'librosa-1.0.0'
    bpm REAL,
    key TEXT,
    scale TEXT,                     -- 'major', 'minor'
    loudness REAL,                  -- integrated LUFS or dB
    danceability REAL,              -- normalized 0.0 to 1.0
    energy REAL,                    -- normalized 0.0 to 1.0
    mood_scores TEXT,               -- JSON: {valence, arousal, happy, sad, aggressive, relaxed}
    embedding BLOB,                 -- IEEE 754 float32 byte array (feature vector)
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_features_bpm ON features(bpm);
CREATE INDEX IF NOT EXISTS idx_features_energy ON features(energy);
CREATE INDEX IF NOT EXISTS idx_features_danceability ON features(danceability);

-- Playlists table: saved playlist definitions and generation rules
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    rules_json TEXT, -- JSON representation of generation parameters (seeds, filters, arc)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Playlist items table: ordered mapping of tracks to playlists
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (playlist_id, position),
    FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);

-- LLM cache table: avoid redundant LLM requests for natural language queries
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. Module Layout

The codebase is organized under `src/vibeplay/` with clear separation of concerns:

```
src/vibeplay/
|-- __init__.py         # Package root, version definition
|-- config.py           # Configuration handling with Pydantic BaseSettings, .env loading
|-- db.py               # SQLite connection management, schema initialization, migrations
|-- scanner.py          # Library traversal, file hashing, mutagen tag extraction
|-- enrichment.py       # AcoustID and MusicBrainz lookups, rate-limiting, tag completion
|-- analysis.py         # Essentia audio analysis with librosa fallback, embedding generation
|-- vectors.py          # Vibe vector formulation, feature scaling, scikit-learn clustering
|-- playlist.py         # Playlist generation engine, vibe arc interpolation, constraints
|-- exporter.py         # M3U, M3U8, JSON, and CSV playlist format serializers
|-- web.py              # FastAPI application, REST endpoints, web UI server
|-- llm.py              # Natural language prompt interpretation and caching
`-- cli.py              # Typer CLI entrypoint exposing user commands
```

---

## 5. CLI Commands

The command-line interface is built with **Typer** and exposed via the `vibeplay` executable:

| Command | Synopsis | Description |
| :--- | :--- | :--- |
| `vibeplay scan` | `vibeplay scan [PATH]` | Scans music folder recursively, computes file hashes, extracts embedded tags, and updates the `tracks` database table. |
| `vibeplay enrich` | `vibeplay enrich [--force] [--limit N]` | Fingerprints tracks with AcoustID and retrieves canonical metadata from MusicBrainz. |
| `vibeplay analyze`| `vibeplay analyze [--force] [--fallback-librosa]` | Analyzes audio waveforms with Essentia (or librosa) to extract BPM, key, energy, danceability, and embeddings. |
| `vibeplay clusters`| `vibeplay clusters [--k N] [--algorithm kmeans\|hdbscan]` | Normalizes vibe vectors, computes clusters, and outputs cluster summary statistics. |
| `vibeplay playlist`| `vibeplay playlist [--seed ID] [--vibe VIBE] [--arc ARC] [--limit N]` | Generates a smart playlist based on a seed song, vibe profile, or trajectory arc. |
| `vibeplay export`  | `vibeplay export <PLAYLIST_ID> [--format m3u\|m3u8\|json] [--out PATH]` | Exports a generated playlist from the database to an M3U/M3U8 file on disk. |
| `vibeplay serve`   | `vibeplay serve [--host HOST] [--port PORT]` | Launches the local FastAPI web server and user interface. |

---

## 6. Phased Roadmap

### Phase 1: Spec and Scaffold (Current)
- Written specification (`SPEC.md`).
- Project scaffold managed by `uv`.
- Stub modules for all pipeline stages.
- Typer CLI with stubbed commands returning "not implemented".
- Pytest test runner with smoke tests.
- Setup instructions and `.gitignore`.

### Phase 2: Scanner Engine
- Recursive filesystem scanner using `pathlib.Path`.
- Extraction of tags via `mutagen` across formats (`.mp3`, `.flac`, `.ogg`, `.m4a`, etc.).
- File hashing and `mtime` change detection for rapid incremental updates.
- SQLite repository implementation in `db.py` and `scanner.py`.
- Strict enforcement of read-only access to user audio directories.

### Phase 3: Metadata Enrichment
- Chromaprint generation via `pyacoustid` / `fpcalc`.
- MusicBrainz lookup via `musicbrainzngs`.
- Rate-limiting mechanisms (1 request per second).
- Fallback fuzzy tag matching.
- Population of `enrichment` table.

### Phase 4: Audio Analysis Pipeline
- Audio decoding and preprocessing.
- Essentia primary extraction (tempo, key, scale, danceability, energy, mood, embeddings).
- Graceful fallback to `librosa` when Essentia is unavailable or fails on specific audio formats.
- Storage of scalar features and binary embedding BLOBs in `features` table.

### Phase 5: Vibe Vectors & Clustering
- Normalization and composite vector formulation (`vibeplay.vectors`).
- Unsupervised clustering via `scikit-learn` (K-Means, HDBSCAN).
- Dimensionality reduction (PCA / UMAP / t-SNE) for cluster visualization.
- Vector distance metrics (cosine similarity, Euclidean distance).

### Phase 6: Playlist Engine & Exporters
- Seed track similarity search.
- Mood trajectory and energy arc interpolation.
- Constraint solving (diversity filters, cooldowns, tempo matching).
- Playlist serialization into `.m3u`, `.m3u8`, JSON, and CSV.

### Phase 7: Local Web UI
- Local FastAPI server (`vibeplay.web`).
- REST endpoints for browsing tracks, clusters, and playlists.
- 2D interactive cluster explorer and playlist preview audio player.

### Phase 8: Optional LLM Layer
- Natural language query parser translating prompts to vibe vectors.
- Integration with Google Gemini API using environment variables.
- LLM response caching in `llm_cache` to minimize token consumption and avoid repeat latency.
