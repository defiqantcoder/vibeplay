import re

# Update essentia_analyzer.py
with open("src/vibeplay/analysis/essentia_analyzer.py", "r") as f:
    content = f.read()

# Add neural mappings for expanded moods
neural_mapping = """
        if len(moods) == 7:
            moods["chill"] = float(np.clip(0.5 * moods.get("relaxed", 0.5) + 0.5 * moods.get("acoustic", 0.5), 0.0, 1.0))
            moods["energetic"] = float(np.clip(0.6 * moods.get("party", 0.5) + 0.4 * moods.get("happy", 0.5), 0.0, 1.0))
            moods["melancholic"] = float(np.clip(0.7 * moods.get("sad", 0.5) + 0.3 * moods.get("relaxed", 0.5), 0.0, 1.0))
            moods["euphoric"] = float(np.clip(0.6 * moods.get("happy", 0.5) + 0.4 * moods.get("party", 0.5), 0.0, 1.0))
            moods["focus"] = float(np.clip(0.5 * moods.get("relaxed", 0.5) + 0.5 * moods.get("acoustic", 0.5), 0.0, 1.0))
            moods["dark"] = float(np.clip(0.6 * moods.get("sad", 0.5) + 0.4 * moods.get("aggressive", 0.5), 0.0, 1.0))
            moods["romantic"] = float(np.clip(0.5 * moods.get("happy", 0.5) + 0.5 * moods.get("relaxed", 0.5), 0.0, 1.0))
            moods["ambient"] = float(np.clip(0.6 * moods.get("relaxed", 0.5) + 0.4 * (1.0 - moods.get("party", 0.5)), 0.0, 1.0))
"""
content = content.replace("return embedding, moods if len(moods) == 7 else None", neural_mapping + "\n        return embedding, moods if len(moods) == 15 else None")


# Add heuristic mappings for expanded moods in fallback
heuristic_mapping = """
        chill = float(np.clip(0.5 * (1.0 - energy) + 0.5 * (1.0 - norm_bpm), 0.0, 1.0))
        energetic = float(np.clip(0.5 * energy + 0.5 * norm_bpm, 0.0, 1.0))
        melancholic = float(np.clip(0.5 * (1.0 - is_major) + 0.5 * (1.0 - energy), 0.0, 1.0))
        euphoric = float(np.clip(0.4 * is_major + 0.3 * energy + 0.3 * danceability, 0.0, 1.0))
        focus = float(np.clip(0.5 * (1.0 - danceability) + 0.3 * (1.0 - abs(norm_bpm - 0.5)) + 0.2 * acoustic, 0.0, 1.0))
        dark = float(np.clip(0.5 * (1.0 - is_major) + 0.5 * energy, 0.0, 1.0))
        romantic = float(np.clip(0.5 * is_major + 0.5 * (1.0 - energy), 0.0, 1.0))
        ambient = float(np.clip(0.5 * (1.0 - energy) + 0.5 * (1.0 - danceability), 0.0, 1.0))
"""
content = content.replace("        mood_scores = {", heuristic_mapping + "\n        mood_scores = {")

dict_keys = """            "chill": round(chill, 4),
            "energetic": round(energetic, 4),
            "melancholic": round(melancholic, 4),
            "euphoric": round(euphoric, 4),
            "focus": round(focus, 4),
            "dark": round(dark, 4),
            "romantic": round(romantic, 4),
            "ambient": round(ambient, 4),"""
content = content.replace("            \"electronic\": round(electronic, 4),\n        }", "            \"electronic\": round(electronic, 4),\n" + dict_keys + "\n        }")

with open("src/vibeplay/analysis/essentia_analyzer.py", "w") as f:
    f.write(content)

# Update librosa_analyzer.py
with open("src/vibeplay/analysis/librosa_analyzer.py", "r") as f:
    content = f.read()

content = content.replace("        mood_scores = {", heuristic_mapping + "\n        mood_scores = {")
content = content.replace("            \"electronic\": round(electronic, 4),\n        }", "            \"electronic\": round(electronic, 4),\n" + dict_keys + "\n        }")

with open("src/vibeplay/analysis/librosa_analyzer.py", "w") as f:
    f.write(content)
