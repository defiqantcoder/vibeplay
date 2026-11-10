import re
from pathlib import Path

WEB_PY = Path("src/vibeplay/web.py")

with open(WEB_PY, "r") as f:
    lines = f.readlines()

def_create_app_start = -1
for i, line in enumerate(lines):
    if line.startswith("def create_app("):
        def_create_app_start = i
        break

print(f"create_app starts at line {def_create_app_start+1}")

routes = []
in_route = False
route_start = -1

for i in range(def_create_app_start, len(lines)):
    line = lines[i]
    if line.strip().startswith("@app."):
        routes.append(i+1)

print(f"Found {len(routes)} routes inside create_app")
