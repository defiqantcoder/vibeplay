with open("src/vibeplay/web.py", "r") as f:
    lines = f.readlines()

# look for the ones that should go into player.py
player_routes = [
    "@app.post(\"/api/player/play-track/{track_id}\"",
    "@app.post(\"/api/player/play-playlist/{playlist_id}\"",
    "@app.post(\"/api/player/toggle\"",
    "@app.post(\"/api/player/seek\"",
    "@app.post(\"/api/player/next\"",
    "@app.post(\"/api/player/prev\"",
    "@app.get(\"/api/player/scrub\"",
    "@app.get(\"/api/player/transport\"",
    "@app.get(\"/api/player/status\"",
    "@app.post(\"/api/player/clear\"",
]
for p in player_routes:
    for i, line in enumerate(lines):
        if p in line:
            print(f"Found {p} at {i+1}")
