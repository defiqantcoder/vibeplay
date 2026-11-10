import re

with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

# Let's extract all routes starting with /api/player and /api/settings from web.py to see which ones are missing in their respective routers
player_routes = re.findall(r'@app\.(?:post|get)\("(/api/player/.*?)"', web)
settings_routes = re.findall(r'@app\.(?:post|get|put)\("(/api/settings.*?)"', web)

print("Player routes in web.py:", player_routes)
print("Settings routes in web.py:", settings_routes)
