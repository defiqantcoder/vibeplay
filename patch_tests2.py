import re

with open("tests/test_phase6_mime_and_ipc.py", "r") as f:
    content = f.read()

import textwrap

old_main_test = """def test_desktop_main_forwards_to_running_instance() -> None:
    \"\"\"Verify vibeplay-desktop %U forwards URIs and exits 0 if an instance is already running.\"\"\"
    with (
        patch("vibeplay.desktop.mime.forward_uris_to_running_instance") as mock_fwd,
        patch("vibeplay.desktop.__main__.DesktopSupervisor") as mock_sup,
    ):
        rc = desktop_main(["--host", "127.0.0.1", "--port", "8765", "file:///tmp/song.flac"])
        assert rc == 0

        import asyncio
        # mock_fwd is a sync MagicMock since we didn't use AsyncMock, but let's just make sure it returns a coroutine returning True

        mock_sup.assert_not_called()"""

new_main_test = """@pytest.mark.asyncio
async def test_desktop_main_forwards_to_running_instance() -> None:
    \"\"\"Verify vibeplay-desktop %U forwards URIs and exits 0 if an instance is already running.\"\"\"
    with (
        patch("vibeplay.desktop.__main__.forward_uris_to_running_instance", new_callable=pytest.MonkeyPatch) as mock_fwd,
        patch("vibeplay.desktop.__main__.DesktopSupervisor") as mock_sup,
    ):
        pass
"""

# Let's just fix test_desktop_main_forwards_to_running_instance by hand to return an awaitable
def fix_test_main(content):
    import re
    # Find the function
    m = re.search(r"def test_desktop_main_forwards_to_running_instance\(\) -> None:(.*?)def test_api_desktop_open_and_telemetry_stream", content, re.DOTALL)

    new_func = """def test_desktop_main_forwards_to_running_instance() -> None:
    \"\"\"Verify vibeplay-desktop %U forwards URIs and exits 0 if an instance is already running.\"\"\"
    async def mock_forward(*args, **kwargs):
        return True

    with (
        patch("vibeplay.desktop.__main__.forward_uris_to_running_instance", side_effect=mock_forward) as mock_fwd,
        patch("vibeplay.desktop.__main__.DesktopSupervisor") as mock_sup,
    ):
        rc = desktop_main(["--host", "127.0.0.1", "--port", "8765", "file:///tmp/song.flac"])
        assert rc == 0
        mock_fwd.assert_called_once_with(["file:///tmp/song.flac"], host="127.0.0.1", port=8765)
        mock_sup.assert_not_called()

"""
    return content[:m.start()] + new_func + content[m.end()-51:] # -51 to not cut off def test_api_...

content = fix_test_main(content)

with open("tests/test_phase6_mime_and_ipc.py", "w") as f:
    f.write(content)
