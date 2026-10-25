with open("src/vibeplay/playlist.py", "r") as f:
    content = f.read()

# Let's just manually replace the whole VIBE_PRESETS dict to be clean

import re
pattern = re.compile(r'VIBE_PRESETS: dict\[str, dict\[str, Any\]\] = \{.*?\}\n\n', re.DOTALL)

clean_presets = """VIBE_PRESETS: dict[str, dict[str, Any]] = {
    "chill": {
        "energy_max": 0.50,
        "mood_min": {"chill": 0.35},
        "danceability_max": 0.65,
    },
    "party": {
        "energy_min": 0.60,
        "mood_min": {"party": 0.35},
        "danceability_min": 0.55,
    },
    "acoustic": {
        "mood_min": {"acoustic": 0.45},
        "energy_max": 0.65,
    },
    "electronic": {
        "mood_min": {"electronic": 0.45},
        "energy_min": 0.45,
    },
    "workout": {
        "energy_min": 0.70,
        "bpm_min": 115.0,
    },
    "melancholic": {
        "mood_min": {"melancholic": 0.35},
        "energy_max": 0.55,
    },
    "energetic": {
        "energy_min": 0.65,
        "mood_min": {"energetic": 0.45},
    },
    "euphoric": {
        "energy_min": 0.60,
        "mood_min": {"euphoric": 0.45},
    },
    "focus": {
        "mood_min": {"focus": 0.45},
    },
    "dark": {
        "mood_min": {"dark": 0.45},
    },
    "romantic": {
        "mood_min": {"romantic": 0.45},
    },
    "ambient": {
        "energy_max": 0.40,
        "mood_min": {"ambient": 0.45},
    },
}

"""

new_content = re.sub(pattern, clean_presets, content, count=1)
with open("src/vibeplay/playlist.py", "w") as f:
    f.write(new_content)
