# tests
with open("tests/test_analysis.py", "r") as f:
    content = f.read()

content = content.replace('    assert "happy" in features.mood_scores', '    assert "happy" in features.mood_scores\n    assert "chill" in features.mood_scores')
with open("tests/test_analysis.py", "w") as f:
    f.write(content)

with open("tests/test_playlist.py", "r") as f:
    content = f.read()

new_moods = """                "chill": 0.5,
                "energetic": 0.5,
                "melancholic": 0.5,
                "euphoric": 0.5,
                "focus": 0.5,
                "dark": 0.5,
                "romantic": 0.5,
                "ambient": 0.5,"""

content = content.replace('"sad": 0.1,', '"sad": 0.1,\n' + new_moods)
with open("tests/test_playlist.py", "w") as f:
    f.write(content)
