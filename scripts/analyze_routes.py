import re
from pathlib import Path

WEB_PY = Path("src/vibeplay/web.py")

with open(WEB_PY, "r") as f:
    content = f.read()

def_create_app_start = content.find("def create_app(")
create_app_content = content[def_create_app_start:]

routes = re.findall(r'    @app\.[a-z]+\("(/api/.*?)"', create_app_content)
prefixes = set()
for r in routes:
    match = re.search(r'(/api/[^/]+)', r)
    if match:
        prefixes.add(match.group(1))

print("Prefixes found in create_app:")
for p in sorted(prefixes):
    print(p)
