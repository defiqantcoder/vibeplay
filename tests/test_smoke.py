"""Smoke tests for vibeplay package and CLI scaffolding."""

import sqlite3
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

import vibeplay
from vibeplay.cli import app
from vibeplay.db import init_db

runner = CliRunner()


def test_package_version() -> None:
    """Verify that vibeplay package exposes version string."""
    assert hasattr(vibeplay, "__version__")
    assert vibeplay.__version__ == "0.1.0"


def test_cli_help() -> None:
    """Verify that vibeplay --help executes successfully and lists all commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "vibeplay [OPTIONS] COMMAND [ARGS]" in result.stdout
    for cmd in [
        "scan",
        "enrich",
        "analyze",
        "clusters",
        "playlist",
        "export",
        "play",
        "serve",
    ]:
        assert cmd in result.stdout


def test_serve_cli_invokes_run_server(monkeypatch: Any) -> None:
    """Verify that vibeplay serve invokes run_server with default arguments."""
    called: dict[str, Any] = {}

    def mock_run_server(
        db_path: Path, host: str = "127.0.0.1", port: int = 8000
    ) -> None:
        called["db_path"] = db_path
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr("vibeplay.web.run_server", mock_run_server)
    result = runner.invoke(app, ["serve", "--port", "8008"])
    assert result.exit_code == 0
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 8008
    assert "Web UI starting" in result.stdout


def test_db_init_schema(tmp_path: Path) -> None:
    """Verify that init_db creates all required SQLite tables and indexes."""
    db_file = tmp_path / "test_vibeplay.db"
    init_db(db_file)

    assert db_file.exists()
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "schema_migrations",
        "tracks",
        "enrichment",
        "features",
        "playlists",
        "playlist_tracks",
        "llm_cache",
        "network_cache",
    }
    assert expected_tables.issubset(tables)

    cursor.execute("SELECT name FROM sqlite_master WHERE type='view'")
    views = {row[0] for row in cursor.fetchall()}
    assert "v_tracks_best_value" in views

    conn.close()
