from typer.testing import CliRunner

from vibeplay import __version__
from vibeplay.cli import app

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"vibeplay {__version__}" in result.stdout


def test_v_flag():
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert f"vibeplay {__version__}" in result.stdout
