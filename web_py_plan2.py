import re
with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

settings_in_web = re.search(r'    @app\.get\("/api/settings"\).*?    return JSONResponse\(\s*content=\{\s*"settings": settings_dict,\s*"peq_presets": peq_presets_list,\s*"settings_path": str\(DEFAULT_DESKTOP_SETTINGS_PATH\),\s*\}\s*\)', web, re.DOTALL)
print("Settings route found in web:", bool(settings_in_web))
