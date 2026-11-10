with open("src/vibeplay/web.py", "r") as f:
    for i, line in enumerate(f):
        if "app.include_router" in line:
            print(f"Line {i+1}: {line.strip()}")
