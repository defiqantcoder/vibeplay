with open("src/vibeplay/analysis/__init__.py", "r") as f:
    content = f.read()

content = content.replace("import os\n", "")
content = content.replace(
    "from typing import Any, Callable", "from typing import Callable"
)

with open("src/vibeplay/analysis/__init__.py", "w") as f:
    f.write(content)
