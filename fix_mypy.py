with open("src/vibeplay/analysis/librosa_analyzer.py", "r") as f:
    content = f.read()

new_content = content.replace("            key_estimate, _ = max(key_scores.items(), key=lambda item: item[1])", "            key_estimate, _ = max(key_scores.items(), key=lambda item: float(item[1]))")

with open("src/vibeplay/analysis/librosa_analyzer.py", "w") as f:
    f.write(new_content)
