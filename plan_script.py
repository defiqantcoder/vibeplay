import re

with open("src/vibeplay/web.py", "r") as f:
    lines = f.readlines()

def_create_app_idx = -1
for i, line in enumerate(lines):
    if line.startswith("def create_app("):
        def_create_app_idx = i
        break

start_search_idx = def_create_app_idx

def extract_routes(prefix):
    routes = []
    for i in range(start_search_idx, len(lines)):
        if lines[i].strip().startswith(f"@app.get(\"{prefix}") or \
           lines[i].strip().startswith(f"@app.post(\"{prefix}") or \
           lines[i].strip().startswith(f"@app.put(\"{prefix}") or \
           lines[i].strip().startswith(f"@app.delete(\"{prefix}"):
            routes.append(i)
    return routes

print(f"Playlist routes: {len(extract_routes('/api/playlist'))}")
