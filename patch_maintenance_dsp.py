import sys

def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # The issue is that the old plugins used `PluginMetadata` which we removed.
    # So we need to convert them to the new `VibePlugin` format which uses `get_manifest`, `on_load`, etc.

    # We will just rewrite them to conform to the new base interface.

    new_content = """from __future__ import annotations
import logging
from typing import Any
from vibeplay.plugins.base import VibePlugin

logger = logging.getLogger(__name__)

class {class_name}(VibePlugin):
    def get_manifest(self) -> dict[str, Any]:
        return {{
            "id": "{id_name}",
            "name": "{name}",
            "description": "{desc}",
            "author": "VibePlay Contributors",
            "version": "0.2.0",
            "icon": "🔧",
            "settings_schema": {{}}
        }}

    def on_load(self, app: Any, config: dict[str, Any]) -> None:
        logger.info("{name} plugin initialized")

    def on_unload(self) -> None:
        logger.info("{name} plugin shut down")
"""

    if "maintenance" in filepath:
        content = new_content.format(class_name="MaintenancePlugin", id_name="maintenance", name="Maintenance Tools", desc="Optional library maintenance tools (duplicate finder and AcoustID/MusicBrainz enrichment)")
    elif "dsp" in filepath:
        content = new_content.format(class_name="DspPlugin", id_name="dsp", name="DSP & Acoustics", desc="Digital Signal Processing convolver and Parametric EQ tools")

    with open(filepath, 'w') as f:
        f.write(content)

if __name__ == '__main__':
    patch_file('src/vibeplay/plugins/maintenance/__init__.py')
    patch_file('src/vibeplay/plugins/dsp/__init__.py')
