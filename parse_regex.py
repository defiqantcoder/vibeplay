import re

with open("src/vibeplay/web.py", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.strip().startswith("@app."):
        print(f"Line {i+1}: {line.strip()}")
        # print the next non-empty line
        j = i + 1
        while j < len(lines):
            if lines[j].strip() and not lines[j].strip().startswith("@app."):
                print(f"  Function: {lines[j].strip()}")
                break
            j += 1
