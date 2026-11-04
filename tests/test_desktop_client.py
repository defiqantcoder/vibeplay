"""Exercise desktop and shared client scripts together and independently."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_desktop_client_behaviors():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for client script behavior checks")
    root = Path(__file__).resolve().parent.parent
    subprocess.run([node, "tests/desktop_client_checks.cjs"], cwd=root, check=True)
