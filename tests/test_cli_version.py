from pathlib import Path

from typer.testing import CliRunner

from vibeplay import __version__
from vibeplay.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    """Verify that vibeplay --version outputs the version string and exits 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"vibeplay {__version__}" in result.stdout


def test_v_flag() -> None:
    """Verify that vibeplay -v outputs the version string and exits 0."""
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert f"vibeplay {__version__}" in result.stdout


def test_version_exits_before_scan(tmp_path: Path) -> None:
    """Verify that --version and -v exit cleanly before executing subcommands like scan."""
    for flag in ("--version", "-v"):
        result = runner.invoke(app, [flag, "scan", str(tmp_path / "missing")])
        assert result.exit_code == 0
        assert f"vibeplay {__version__}" in result.stdout
