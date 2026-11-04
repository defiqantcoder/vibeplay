import re

with open("src/vibeplay/desktop/__main__.py", "r") as f:
    content = f.read()

# Add import for setup_logging
import_statement = "from vibeplay.desktop.app import setup_logging\n"

# Replace logging.basicConfig block
pattern = r"    log_level = logging\.DEBUG if args\.debug else logging\.INFO\n    logging\.basicConfig\(\n        level=log_level,\n        format=\"%\(asctime\)s \[%\(levelname\)s\] %\(name\)s: %\(message\)s\",\n    \)"
replacement = "    setup_logging(args.debug)"

# Need to place the import statement near the top. Let's put it after the other imports.
# Find `from vibeplay.desktop.runner import DesktopRunner` and insert it.
content = content.replace("from vibeplay.desktop.runner import DesktopRunner", "from vibeplay.desktop.app import setup_logging\nfrom vibeplay.desktop.runner import DesktopRunner")
content = re.sub(pattern, replacement, content)

with open("src/vibeplay/desktop/__main__.py", "w") as f:
    f.write(content)
