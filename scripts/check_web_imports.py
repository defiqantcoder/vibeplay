with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

import re
print("Imports from routers:", re.findall(r'from vibeplay.routers.* import.*', web))
