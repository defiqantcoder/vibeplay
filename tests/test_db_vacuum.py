import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibeplay.cli import app
from vibeplay.db import init_db, vacuum_db

runner = CliRunner()


def test_vacuum_db_function(tmp_path: Path):
    """Test that vacuum_db function executes correctly."""
    db_path = tmp_path / "vibeplay.db"
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    init_db(db_path)

    # Insert some dummy data to ensure DB is initialized and has content
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tracks (path, duration, mtime, size, hash) VALUES ('dummy.mp3', 10, 1000.0, 2000, 'hashvalue')")
    conn.commit()

    # The actual test
    try:
        vacuum_db(conn)
    except sqlite3.OperationalError as e:
        pytest.fail(f"vacuum_db raised sqlite3.OperationalError: {e}")
    finally:
        conn.close()

    assert db_path.exists()
    assert db_path.stat().st_size > 0


def test_cache_vacuum_cli_command(tmp_path: Path):
    """Test the 'cache vacuum' CLI command."""
    db_path = tmp_path / "vibeplay.db"
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    init_db(db_path)
    conn.close()

    result = runner.invoke(app, ["cache", "vacuum", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "Database successfully vacuumed and optimized" in result.stdout
