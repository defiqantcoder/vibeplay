from typer.testing import CliRunner

from vibeplay import __version__
from vibeplay.cli import app

runner = CliRunner()


def test_cli_version_flag() -> None:
    """Verify that vibeplay --version outputs the version string and exits 0."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"vibeplay {__version__}" in result.stdout


def test_cli_v_flag() -> None:
    """Verify that vibeplay -v outputs the version string and exits 0."""
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert f"vibeplay {__version__}" in result.stdout
