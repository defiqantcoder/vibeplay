import re
from pathlib import Path

# This script moves code from web.py to individual routers.
# Because this is a very long operation that requires a lot of care,
# I will do it programmatically using a Python script.

# Read web.py
with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

# First we need to parse out all the routes from create_app in web.py
# A route starts with @app. and ends right before the next @app., or the end of the create_app function.
