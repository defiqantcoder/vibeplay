with open("src/vibeplay/routers/player.py", "r") as f:
    player = f.read()

import re
player_routes_in_router = re.findall(r'@router\.(?:post|get)\("(.*?)"', player)
print("Player routes in player.py:", player_routes_in_router)

with open("src/vibeplay/routers/settings.py", "r") as f:
    settings = f.read()

settings_routes_in_router = re.findall(r'@router\.(?:post|get|put)\("(.*?)"', settings)
print("Settings routes in settings.py:", settings_routes_in_router)
