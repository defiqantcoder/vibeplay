import importlib
import sys


def test_imports_sanity():
    for module in ("vibeplay.cli", "vibeplay.player", "vibeplay.desktop", "vibeplay.web"):
        importlib.import_module(module)
        assert module in sys.modules
