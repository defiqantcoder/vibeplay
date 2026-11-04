🎯 **What:** The code health issue addressed
Extracted the single file processing (hashing, metadata parsing, and track insertion/updating) from the `scan_directory` main loop into a separate helper method `_sync_single_file`.

💡 **Why:** How this improves maintainability
The inner loop of `scan_directory` was excessively long due to the many keyword arguments passed to `insert_track` and `update_track`. Extracting this to `_sync_single_file` significantly reduces the complexity of `scan_directory`, making its overall logic (discovering files, determining delta updates, detecting removed files) much easier to follow at a glance.

✅ **Verification:** How you confirmed the change is safe
Ran the full test suite (`uv run pytest`) and verified it passes cleanly. The `tests/test_scanner.py` passed both before and after the refactoring. Code styling is preserved through `uv run ruff check` and typing holds via `uv run mypy`. The commit does not include any unintended artifacts.

✨ **Result:** The improvement achieved
A clear separation of concerns: `scan_directory` orchestrates the tree walk and update logic, while `_sync_single_file` handles the dense specifics of writing a single track to the database.
