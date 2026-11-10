import re
from pathlib import Path

WEB_PY = Path("src/vibeplay/web.py")

with open(WEB_PY, "r") as f:
    content = f.read()

# Let's count how many @app routes there are
routes = re.findall(r'    @app\.[a-z]+\("/api/(.*?)"', content)

# Show what remains in `create_app`
print("Routes in create_app:")
for r in sorted(set(routes)):
    print(r)
