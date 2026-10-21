with open("src/vibeplay/analysis/librosa_analyzer.py", "r") as f:
    content = f.read()

new_content = content.replace("        best_key, best_scale = max(scores, key=scores.get)", "        best_key, best_scale = max(scores, key=lambda k: scores[k])")

with open("src/vibeplay/analysis/librosa_analyzer.py", "w") as f:
    f.write(new_content)
