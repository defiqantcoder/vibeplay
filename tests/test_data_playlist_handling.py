import pytest

from vibeplay.playlist import PlaylistRuleConfig

def test_playlist_rule_config():
    config = PlaylistRuleConfig(
        vibe="chill",
        energy_min=0.1,
        energy_max=0.5,
        bpm_min=90.0,
        bpm_max=110.0,
        key="8A",
        genre_include=["Lo-Fi", "Ambient"],
        genre_exclude=["Metal"]
    )
    assert config.vibe == "chill"
    assert config.energy_min == 0.1
    assert config.energy_max == 0.5
    assert config.bpm_min == 90.0
    assert config.bpm_max == 110.0
    assert config.key == "8A"
    assert config.genre_include == ["Lo-Fi", "Ambient"]
    assert config.genre_exclude == ["Metal"]
