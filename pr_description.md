🧪 [testing improvement] Add tests for `insert_track`

🎯 **What:**
The `insert_track` function in `src/vibeplay/db.py` lacked a unit test. A new test file `tests/test_db.py` was created to test this functionality.

📊 **Coverage:**
The test covers the happy path scenario for `insert_track`, ensuring that:
- It successfully inserts a track record into the `tracks` table.
- It handles an in-memory SQLite connection correctly.
- The returned `track_id` is valid.
- The inserted data can be successfully retrieved and matches the input data.

✨ **Result:**
Test coverage has increased, making the database operations more reliable and providing a safety net for future refactoring of track insertion logic. The codebase is also free of previous unused import warnings identified by `ruff`.
