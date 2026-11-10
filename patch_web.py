import re
from pathlib import Path

WEB_PY = Path("src/vibeplay/web.py")

with open(WEB_PY, "r") as f:
    content = f.read()

# I need to remove the routes from `web.py` that have already been moved to `player.py` and `settings.py`.
# wait, have they been fully moved to `player.py` and `settings.py`?
# In `player.py`, I saw:
# @router.get("/output/profiles")
# @router.post("/output", ...)
# @router.post("/volume", ...)
# @router.post("/volume-step", ...)
# @router.post("/mute-toggle", ...)
# But NOT:
# @app.post("/api/player/play-track/{track_id}"
# @app.post("/api/player/play-playlist/{playlist_id}"
# @app.post("/api/player/toggle"
# @app.post("/api/player/seek"
# @app.post("/api/player/next"
# @app.post("/api/player/prev"
# @app.get("/api/player/scrub"
# @app.get("/api/player/transport"
# @app.get("/api/player/status"
# @app.post("/api/player/clear"
