with open("src/vibeplay/web.py", "r") as f:
    lines = f.readlines()

# look for the ones that should go into settings.py
settings_routes = [
    "@app.get(\"/api/settings\"",
    "@app.get(\"/api/settings/modal\"",
    "@app.get(\"/api/settings/gemini\"",
    "@app.get(\"/api/settings/api-key\"",
    "@app.post(\"/api/settings/gemini\"",
    "@app.post(\"/api/settings/api-key\"",
    "@app.post(\"/api/settings\"",
    "@app.put(\"/api/settings\"",
]
for p in settings_routes:
    for i, line in enumerate(lines):
        if p in line:
            print(f"Found {p} at {i+1}")
