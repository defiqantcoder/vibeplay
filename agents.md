# VibePlay AI Developer Instructions

## Project Context
VibePlay is an audiophile-grade desktop music player focusing on bit-perfect playback, lossless FLAC, and smart playlists. 

## UI Implementation Rules (Strict)
1. **Never Hardcode Mock Data:** When translating UI mockups (like Stitch exports) to code, NEVER hardcode the example data (crates, songs, artists, albums). 
2. **Template Driven:** You must use backend template loops (e.g., Jinja `{% for track in tracks %}`) to render lists and grids dynamically. Assume the Python backend provides the context variables.
3. **Empty States:** Always account for and implement the empty state (`{% if not tracks %}`) alongside the populated state.
4. **HTMX Integration:** Use HTMX (`hx-get`, `hx-post`, `hx-target`, `hx-swap`) for dynamic state changes, modal loading, and playback controls without full page reloads.

## Python Backend Rules
- Keep the presentation layer completely decoupled from the data and DSP layers.
- Do not generate fake database seeding scripts unless explicitly asked.
