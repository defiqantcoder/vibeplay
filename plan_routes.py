import re

with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

# All decorators inside create_app
routes = re.findall(r'@app\.(?:get|post|put|delete)\("([^"]+)"', web)
print(f"Total routes in web.py: {len(routes)}")

prefix_counts = {}
for r in routes:
    prefix = '/'.join(r.split('/')[:3]) # e.g. /api/player
    prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

print("\nPrefix counts:")
for p, c in sorted(prefix_counts.items(), key=lambda x: -x[1]):
    print(f"{p}: {c}")
