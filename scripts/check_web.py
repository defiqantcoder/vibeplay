with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

import re
print("Matches in web.py for settings:", bool(re.search(r'def api_get_settings', web)))
print("Matches in web.py for volume:", bool(re.search(r'def api_player_volume', web)))
print("Includes player_router:", bool(re.search(r'app.include_router\(player_router\)', web)))
print("Includes settings_router:", bool(re.search(r'app.include_router\(settings_router\)', web)))
