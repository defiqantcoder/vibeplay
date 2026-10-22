# VibePlay Workspace Rules

## 1. UI & Stitch Design System Fidelity
- Always consult `DESIGN.md` ("God of Ink" theme tokens, typography, and layout principles) before creating or modifying HTML templates (`src/vibeplay/templates/`) or UI modules (`src/vibeplay/ui/`).
- Do not rely solely on local screenshots in the repository. Query the Stitch MCP server (`projectId: "4886383833648930957"`) via `list_screens` and `get_screen` to verify all designed screens (`2f505b68a45649a3b593fc86d10c4bb3`, `316d6d8658bf41eea50a022675edab79`, `c2e6c5d44a5d494f852b50766a1ba04d`) and micro-visualizers are accounted for.

## 2. FastAPI, Pydantic v2 & `vibe_dsp` Guardrails
- **Pydantic v2 `ValidationError` in `JSONResponse`**: When returning `pydantic.ValidationError` details in FastAPI `JSONResponse` (especially from models with custom `@field_validator` rules like `DesktopSettings`), always call `val_err.errors(include_context=False)`. Omitting `include_context=False` leaves raw `ValueError` instances inside `ctx["error"]`, which raises `TypeError: Object of type ValueError is not JSON serializable`.
- **`vibe_dsp.peq` Return Contracts**:
  - `vibe_dsp.peq.list_available_presets()` returns `list[dict[str, Any]]` (each dict has `"name"`, `"preamp_db"`, `"bands"`), not `list[str]`.
  - `vibe_dsp.peq.lookup_autoeq_model(preset_id, allow_network=False)` returns a `PEQProfile` object exposing `.calculated_preamp` and `.filters`.
- **Desktop Security Invariants**:
  - The desktop web server must only bind to loopback (`127.0.0.1` or `localhost`), enforced via `validate_loopback_host()`.
  - Persisted desktop configuration files (`desktop_settings.json`) must be written atomically via a temporary file and locked down with `0o600` (`chmod 600`) permissions.

## 3. Testing & Fixture Isolation
- **Settings Isolation**: Any test exercising `/api/settings` or `DesktopSettings` persistence must override `cfg.desktop_settings_path` (or pass `path=tmp_path / "desktop_settings.json"`) so tests never read or mutate `~/.config/vibeplay/desktop_settings.json`.
- **SQLite Schema Constraints**: When seeding `tracks` and `features` tables in test fixtures, always provide `hash` (`NOT NULL` on `tracks`) and `analyzer_version` (`NOT NULL` on `features`).
