with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

import re
# check player volume route in web.py vs player.py
m1 = re.search(r'async def api_player_volume\(.*?\) -> Response:\n(.*?)(?=\n    @app)', web, re.DOTALL)
if m1:
    print("In web.py: api_player_volume length:", len(m1.group(1)))

with open("src/vibeplay/routers/player.py", "r") as f:
    player = f.read()

m2 = re.search(r'async def api_post_volume\(.*?\) -> Response:\n(.*?)(?=\n@router)', player, re.DOTALL)
if m2:
    print("In player.py: api_post_volume length:", len(m2.group(1)))
