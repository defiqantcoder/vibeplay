with open("src/vibeplay/web.py", "r") as f:
    content = f.read()

content = content.replace("Detail: Unauthorized: Invalid or missing API key. Provide via X-API-Key header, Authorization Bearer token, or ?api_key=...", "Detail: Unauthorized: Invalid or missing API key. Provide via X-API-Key header or Authorization Bearer token.")

content = content.replace("Unauthorized: Invalid or missing API key. Provide via X-API-Key header, Authorization Bearer token, or ?api_key=...", "Unauthorized: Invalid or missing API key. Provide via X-API-Key header or Authorization Bearer token.")

with open("src/vibeplay/web.py", "w") as f:
    f.write(content)
