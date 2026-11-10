import re

with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

# Let's count the number of routes for each
player_routes = re.findall(r'(\s*@app\.(?:post|get)\("/api/player/.*?\n(?:    |@).*?(?=\n    @app|\n    from|\n    app\.include_router))', web, re.DOTALL)
print(f"Player routes in web: {len(player_routes)}")

# This regex is tricky because of the indentation and arbitrary python code inside the functions.
