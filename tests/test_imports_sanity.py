import importlib
import sys


def test_imports_sanity():
    importlib.import_module("vibeplay.cli")
    importlib.import_module("vibeplay.player")
    importlib.import_module("vibeplay.desktop")
    importlib.import_module("vibeplay.web")

    assert "vibeplay.cli" in sys.modules
    assert "vibeplay.player" in sys.modules
    assert "vibeplay.desktop" in sys.modules
    assert "vibeplay.web" in sys.modules
