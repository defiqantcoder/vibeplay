# Vibeplay Performance Analysis & Recommendations

This report outlines performance bottlenecks identified in `src/vibeplay/db.py`, related query-heavy paths, schema design, and python transaction patterns. It also provides specific, actionable recommendations for optimizing these pathways to better support large music libraries and frequent UI refreshes.

## 1. Redundant Self-Joins with `v_tracks_best_value`

**Issue:**
In `web.py` (`get_filtered_tracks`) and `db.py` (`get_playlist_tracks`), the application joins the base `tracks` table against the `v_tracks_best_value` view.
Example from `web.py`:
```sql
SELECT ...
FROM tracks t
LEFT JOIN v_tracks_best_value v ON t.id = v.track_id
LEFT JOIN features f ON t.id = f.track_id
```
Because `v_tracks_best_value` is defined as a view joining `tracks` and `enrichment`, SQLite is forced to do a redundant, expensive self-join of the `tracks` table.

**Recommendation:**
Refactor these queries to select directly from `v_tracks_best_value` instead of joining `tracks` against it. Since `v_tracks_best_value` already exposes `track_id`, `path`, `duration`, `status`, etc., this removes the self-join:
```sql
SELECT ...
FROM v_tracks_best_value v
LEFT JOIN features f ON v.track_id = f.track_id
WHERE v.track_status = 'active'
```

## 2. Inefficient Checksum Logic (`get_features_checksum`)

**Issue:**
`get_features_checksum` in `db.py` fetches the *entire* `features` table into memory to calculate a hash:
```python
cursor.execute("SELECT track_id, analyzer_version, bpm, loudness, danceability, energy, mood_scores, length(embedding) FROM features ORDER BY track_id ASC")
rows = cursor.fetchall()
hasher = hashlib.sha256()
for row in rows: ...
```
For large libraries, iterating over thousands of rows locally in Python creates huge memory overhead and I/O bottlenecks.

**Recommendation:**
Shift this computation to SQLite, or utilize aggregate data. Adding an `updated_at` column to `features` allows fetching the max timestamp instead:
```sql
SELECT COUNT(*), MAX(analyzed_at) FROM features;
```
If a full data checksum is strictly required, generate it using SQLite's aggregate functions to avoid pulling data into Python, though counting rows and comparing maximum timestamps is vastly more performant for cache invalidation (`vectors.py`).

## 3. High Memory Footprint in Playlist Generation

**Issue:**
In `src/vibeplay/playlist.py`, `generate_playlist` loads the rich metadata and full features for *every active track* into memory:
```python
all_tracks_rows = get_tracks_with_features(conn)
rich_tracks_by_id: dict[int, dict[str, Any]] = {}
for r in all_tracks_rows: ...
```
`get_tracks_with_features` also pulls in the large `embedding` BLOB for every track. The python dictionary allocations will cause major latency when scaling up to massive libraries.

**Recommendation:**
First, `get_tracks_with_features` shouldn't pull the `embedding` BLOB unless it's strictly needed, as it significantly increases memory transfer. Second, instead of fetching *all* tracks, the initial clustering/filtering logic in `generate_playlist` should yield a narrowed set of candidate `track_id`s, and a new query `get_tracks_with_features_by_ids(conn, ids)` should pull rich metadata *only* for the filtered subset.

## 4. UI Refresh Expensive Queries (`web.py`)

**Issue:**
The main web index makes several non-indexed, table-scanning queries that run on every page load:
1. `SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM tracks WHERE status = 'active'`
2. `SELECT DISTINCT COALESCE(v.artist, t.artist) AS artist_name FROM tracks t LEFT JOIN v_tracks_best_value v ... ORDER BY LOWER(COALESCE(v.artist, t.artist)) ASC`

The redundant `COALESCE` wrapping `v.artist` (which already coalesces canonical vs original) adds overhead. Furthermore, extracting `DISTINCT` records and sorting them by `LOWER()` requires a full temporary table and sorting pass.

**Recommendation:**
1. **Remove redundant coalescing:** Query `SELECT DISTINCT artist FROM v_tracks_best_value WHERE track_status = 'active' ORDER BY LOWER(artist) ASC`
2. **Expression Indexes:** Add indices to accelerate these specific sorts:
   `CREATE INDEX idx_tracks_artist_lower ON tracks(LOWER(artist));`
3. **App-level Caching:** Cache the total tracks count, duration, and artist list in memory. Invalidate only when library scans or edits occur.

## 5. Suboptimal Indexing and Missing Covered Queries

**Issue:**
While basic indexes exist (`idx_features_bpm`, `idx_enrichment_status`), queries in `web.py` that filter by mood thresholds and sorting combinations fall back to full table scans.

**Recommendation:**
- Create composite indices on `features` aligning with frequent filter/sort combos, such as: `CREATE INDEX idx_features_bpm_energy ON features(bpm, energy);`
- Create an index for track status filtering since it is heavily used: `CREATE INDEX idx_tracks_status_id ON tracks(status, id);` (allows covered sequential scans).

## 6. Connection Overhead & Transaction Patterns

**Issue:**
Functions frequently use `with get_connection(...) as conn:`. While SQLite WAL mode is enabled, creating a fresh connection object repeatedly causes a small but measurable overhead under high load (e.g. web UI endpoints).

**Recommendation:**
Use a connection pool (e.g. via `sqlalchemy` or by caching thread-local connections) instead of opening a raw connection on every query operation.
