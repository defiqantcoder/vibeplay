import sys


def test_imports_sanity():
    import vibeplay.cli
    import vibeplay.desktop
    import vibeplay.player
    import vibeplay.web

    assert vibeplay.cli is sys.modules["vibeplay.cli"]
    assert vibeplay.player is sys.modules["vibeplay.player"]
    assert vibeplay.desktop is sys.modules["vibeplay.desktop"]
    assert vibeplay.web is sys.modules["vibeplay.web"]
