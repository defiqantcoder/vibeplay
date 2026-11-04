import ast

with open("src/vibeplay/desktop/runner.py", "r") as f:
    content = f.read()

# Add imports from vibeplay.desktop.app
imports = [node for node in ast.parse(content).body if isinstance(node, ast.ImportFrom) and node.module == "vibeplay.desktop.app"]
existing = {alias.name for node in imports for alias in node.names if alias.asname in (None, alias.name)}
missing = [name for name in ("setup_gtk", "run_webview") if name not in existing]
if missing:
    anchor = "from vibeplay.desktop.security import is_loopback_host, validate_loopback_host"
    content = content.replace(anchor, f"from vibeplay.desktop.app import {', '.join(missing)}\n" + anchor)

# Replace gtk setup and webview setup block inside `start`
old_gtk_block = """        # Setup GTK application name, WM_CLASS, and window icon
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            from gi.repository import GLib, Gtk

            GLib.set_prgname("vibeplay")
            GLib.set_application_name("VibePlay")
            icon_file = resolve_app_icon_path()
            if icon_file and icon_file.is_file():
                try:
                    Gtk.Window.set_default_icon_from_file(str(icon_file))
                except Exception:
                    pass
            Gtk.Window.set_default_icon_name("vibeplay")
        except Exception as err:
            logger.debug("Could not apply GTK app icon attributes: %s", err)"""

new_gtk_block = """        # Setup GTK application name, WM_CLASS, and window icon
        setup_gtk()"""

old_webview_block = """        try:
            import webview

            url = f"http://{self.host}:{self.port}/"
            self.window = webview.create_window(
                title=WINDOW_TITLE,
                url=url,
                width=DEFAULT_WINDOW_WIDTH,
                height=DEFAULT_WINDOW_HEIGHT,
                min_size=(DEFAULT_WINDOW_MIN_WIDTH, DEFAULT_WINDOW_MIN_HEIGHT),
                text_select=True,
            )
            webview.start()
        except Exception as err:
            logger.error("PyWebView GUI failure: %s", err)
        finally:
            self.stop()"""

new_webview_block = """        try:
            self.window = run_webview(self.host, self.port)
        finally:
            self.stop()"""

content = content.replace(old_gtk_block, new_gtk_block)
content = content.replace(old_webview_block, new_webview_block)

with open("src/vibeplay/desktop/runner.py", "w") as f:
    f.write(content)
