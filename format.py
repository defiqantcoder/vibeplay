with open("src/vibeplay/cli.py", "r") as f:
    lines = f.readlines()
with open("src/vibeplay/cli.py", "w") as f:
    for line in lines:
        if line.startswith("warnings.filterwarnings"):
            continue
        if line.startswith("import typer"):
            f.write("import warnings\nwarnings.filterwarnings(\"ignore\", message=\".*StarletteDeprecationWarning.*\")\nwarnings.filterwarnings(\"ignore\", category=DeprecationWarning, module=\"starlette.*\")\n")
        f.write(line)
