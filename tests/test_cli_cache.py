"""Tests for cache CLI commands."""
from pathlib import Path

from typer.testing import CliRunner

from vibeplay.cli import app
from vibeplay.db import get_connection, init_db, set_cached_response, set_llm_cache

runner = CliRunner()


def test_cli_cache_cleanup(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cache_cleanup.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        set_llm_cache(conn, "old_llm", "old prompt", "old response", "gemini-3.8-flash")
        conn.execute("UPDATE llm_cache SET created_at = datetime('now', '-45 days') WHERE prompt_hash = 'old_llm'")
        set_cached_response(conn, "old_net", "acoustid", '{"status": "old"}')
        conn.execute("UPDATE network_cache SET created_at = datetime('now', '-45 days') WHERE cache_key = 'old_net'")

    result = runner.invoke(app, ["cache", "cleanup", "--db", str(db_file), "--days", "30"])

    assert result.exit_code == 0
    assert "Cache cleanup completed (threshold: 30 days):" in result.stdout
    assert "LLM Prompts Pruned:     1" in result.stdout
    assert "Network Records Pruned: 1" in result.stdout

    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM llm_cache")
        assert cursor.fetchone()[0] == 0


def test_cli_cache_purge_interactive_abort(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cache_purge_abort.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        set_llm_cache(conn, "h1", "p1", "r1", "m1")

    result = runner.invoke(app, ["cache", "purge", "--db", str(db_file)], input="n\n")

    assert result.exit_code == 0
    assert "Aborted" in result.stdout

    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM llm_cache")
        assert cursor.fetchone()[0] == 1


def test_cli_cache_purge_interactive_confirm(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cache_purge_confirm.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        set_llm_cache(conn, "h1", "p1", "r1", "m1")
        set_cached_response(conn, "k1", "e1", "r1")

    result = runner.invoke(app, ["cache", "purge", "--db", str(db_file)], input="y\n")

    assert result.exit_code == 0
    assert "All caches purged:" in result.stdout
    assert "LLM Prompts Deleted:     1" in result.stdout
    assert "Network Records Deleted: 1" in result.stdout

    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM llm_cache")
        assert cursor.fetchone()[0] == 0


def test_cli_cache_purge_yes_flag(tmp_path: Path) -> None:
    db_file = tmp_path / "test_cache_purge_yes.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        set_llm_cache(conn, "h1", "p1", "r1", "m1")
        set_cached_response(conn, "k1", "e1", "r1")

    result = runner.invoke(app, ["cache", "purge", "--yes", "--db", str(db_file)])

    assert result.exit_code == 0
    assert "All caches purged:" in result.stdout
    assert "LLM Prompts Deleted:     1" in result.stdout
    assert "Network Records Deleted: 1" in result.stdout

    with get_connection(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM llm_cache")
        assert cursor.fetchone()[0] == 0
