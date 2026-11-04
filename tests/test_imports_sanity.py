import sys


def test_imports_sanity():

    assert "vibeplay.cli" in sys.modules
    assert "vibeplay.player" in sys.modules
    assert "vibeplay.desktop" in sys.modules
    assert "vibeplay.web" in sys.modules
