import re
from pathlib import Path

WEB_PY = Path("src/vibeplay/web.py")

with open(WEB_PY, "r") as f:
    content = f.read()

# Let's count how many @app routes there are
routes = re.findall(r'    @app\.[a-z]+\("/api/.*?"\)', content)
print(f"Found {len(routes)} api routes.")

# List of prefixes to see how we could group them
prefixes = set()
for r in routes:
    match = re.search(r'"(/api/[a-z]+)[/"]', r)
    if match:
        prefixes.add(match.group(1))

print(f"Prefixes: {prefixes}")
