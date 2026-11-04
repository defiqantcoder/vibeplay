import re

with open("src/vibeplay/desktop/runner.py", "r") as f:
    content = f.read()

resolve_app_icon_path_str = """def resolve_app_icon_path() -> Path | None:
    \"\"\"Locate the VibePlay application icon file for window decoration.\"\"\"
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        for p in (
            meipass / "packaging" / "icons" / "vibeplay.svg",
            meipass / "vibeplay.svg",
            meipass / "vibeplay" / "static" / "vibeplay.svg",
        ):
            if p.is_file():
                return p

    user_icon = Path("~/.local/share/icons/hicolor/scalable/apps/vibeplay.svg").expanduser()
    if user_icon.is_file():
        return user_icon

    system_icon = Path("/usr/share/icons/hicolor/scalable/apps/vibeplay.svg")
    if system_icon.is_file():
        return system_icon

    repo_icon = Path(__file__).resolve().parent.parent.parent.parent / "packaging" / "icons" / "vibeplay.svg"
    if repo_icon.is_file():
        return repo_icon

    pkg_icon = Path(__file__).resolve().parent.parent / "static" / "vibeplay.svg"
    if pkg_icon.is_file():
        return pkg_icon

    return None"""

content = content.replace(resolve_app_icon_path_str, "")

# Add import for resolve_app_icon_path to runner.py to avoid breaking external imports (like __init__.py)
content = content.replace("from vibeplay.desktop.app import run_webview, setup_gtk", "from vibeplay.desktop.app import run_webview, setup_gtk, resolve_app_icon_path")

with open("src/vibeplay/desktop/runner.py", "w") as f:
    f.write(content)


with open("src/vibeplay/desktop/app.py", "r") as f:
    app_content = f.read()

app_content = app_content.replace("from vibeplay.desktop.runner import resolve_app_icon_path", "from pathlib import Path\n")
app_content = app_content.replace("def setup_logging", resolve_app_icon_path_str + "\n\n\ndef setup_logging")

with open("src/vibeplay/desktop/app.py", "w") as f:
    f.write(app_content)
