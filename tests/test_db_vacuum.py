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


@pytest.mark.parametrize("use_default", [False, True])
def test_cache_vacuum_rejects_missing_database(tmp_path, monkeypatch, use_default):
    from types import SimpleNamespace
    from unittest.mock import Mock

    db_path = tmp_path / "missing.db"
    monkeypatch.setattr("vibeplay.cli.get_settings", lambda: SimpleNamespace(db_path=db_path))
    get_connection = Mock()
    monkeypatch.setattr("vibeplay.db.get_connection", get_connection)
    args = ["cache", "vacuum"]
    if not use_default:
        args += ["--db", str(db_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "Database not found" in result.stdout
    assert "successfully" not in result.stdout
    get_connection.assert_not_called()
    assert not db_path.exists()


@pytest.mark.parametrize("busy_after_vacuum", [False, True])
def test_vacuum_busy_checkpoint_exhausts_retries(monkeypatch, busy_after_vacuum):
    from unittest.mock import Mock

    monkeypatch.setattr("vibeplay.db.time.sleep", lambda _: None)
    conn = Mock()
    cursor = conn.cursor.return_value
    cursor.fetchone.side_effect = [(0, 0, 0), (1, 1, 0)] * 6 if busy_after_vacuum else [(1, 1, 0)] * 6
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        vacuum_db(conn)
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert statements.count("VACUUM;") == (6 if busy_after_vacuum else 0)


def test_vacuum_retries_busy_checkpoint(monkeypatch):
    from unittest.mock import Mock

    monkeypatch.setattr("vibeplay.db.time.sleep", lambda _: None)
    conn = Mock()
    cursor = conn.cursor.return_value
    cursor.fetchone.side_effect = [(1, 1, 0), (0, 0, 0), (0, 0, 0)]
    vacuum_db(conn)
    assert [call.args[0] for call in cursor.execute.call_args_list] == [
        "PRAGMA wal_checkpoint(TRUNCATE);",
        "PRAGMA wal_checkpoint(TRUNCATE);",
        "VACUUM;",
        "PRAGMA wal_checkpoint(TRUNCATE);",
    ]


def test_vacuum_truncates_wal_with_other_connection_open(tmp_path):
    db_path = tmp_path / "wal.db"
    with sqlite3.connect(db_path) as conn, sqlite3.connect(db_path) as other:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE payload (value BLOB)")
        conn.executemany("INSERT INTO payload VALUES (zeroblob(4096))", [()] * 100)
        conn.commit()
        conn.execute("DELETE FROM payload")
        conn.commit()
        other.execute("SELECT count(*) FROM payload").fetchone()
        size_before = db_path.stat().st_size + Path(f"{db_path}-wal").stat().st_size
        vacuum_db(conn)
        assert Path(f"{db_path}-wal").stat().st_size == 0
        assert db_path.stat().st_size < size_before
        assert other.execute("SELECT count(*) FROM payload").fetchone()[0] == 0


def test_cache_vacuum_does_not_report_checkpoint_failure_as_success(tmp_path, monkeypatch):
    db_path = tmp_path / "vibeplay.db"
    init_db(db_path)

    def fail_checkpoint(conn):
        raise sqlite3.OperationalError("database is locked: WAL checkpoint is busy")

    monkeypatch.setattr("vibeplay.db.vacuum_db", fail_checkpoint)
    result = runner.invoke(app, ["cache", "vacuum", "--db", str(db_path)])
    assert result.exit_code != 0
    assert isinstance(result.exception, sqlite3.OperationalError)
    assert "successfully" not in result.stdout
