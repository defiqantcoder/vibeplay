with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

import re
m = re.search(r'    @app\.get\("/api/settings"\)\n    async def api_get_settings\(request: Request\) -> Response:(.*?)(?=\n    @app\.get\("/api/settings/modal)', web, re.DOTALL)
if m:
    print(m.group(0))
