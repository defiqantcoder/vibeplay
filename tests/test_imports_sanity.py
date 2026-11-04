import pytest
import sys

def test_imports_sanity():
    import vibeplay.cli
    import vibeplay.player
    import vibeplay.desktop
    import vibeplay.web

    assert 'vibeplay.cli' in sys.modules
    assert 'vibeplay.player' in sys.modules
    assert 'vibeplay.desktop' in sys.modules
    assert 'vibeplay.web' in sys.modules
