import re

with open("tests/test_phase6_mime_and_ipc.py", "r") as f:
    content = f.read()

# pytest.mark.asyncio requires pytest-asyncio, but if the project uses anyio natively, we can use @pytest.mark.anyio
# Let's check pyproject.toml if pytest-asyncio is installed. I remember looking at it, it was just "pytest>=9.1.1".
# But wait, anyio is in the collected plugins. Let's see if we can use pytest.mark.anyio instead of pytest.mark.asyncio.
content = content.replace("@pytest.mark.asyncio", "@pytest.mark.anyio")

# And for test_desktop_main_forwards_to_running_instance, the module is vibeplay.desktop.mime
content = content.replace("patch(\"vibeplay.desktop.__main__.forward_uris_to_running_instance\", side_effect=mock_forward)",
                          "patch(\"vibeplay.desktop.mime.forward_uris_to_running_instance\", side_effect=mock_forward)")

with open("tests/test_phase6_mime_and_ipc.py", "w") as f:
    f.write(content)
