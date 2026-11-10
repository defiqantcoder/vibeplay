import re
from pathlib import Path

WEB_PY = Path("src/vibeplay/web.py")

with open(WEB_PY, "r") as f:
    lines = f.readlines()

# let's just delete the settings functions from web.py, since they are already duplicated in settings.py
# then we'll check if they are actually used from there.
