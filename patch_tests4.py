import re

with open("tests/test_phase6_mime_and_ipc.py", "r") as f:
    content = f.read()

# I assigned a python function `mock_post` to `mock_client.post`, which does not have `.called`. I should use an AsyncMock.
# But unittest.mock in Python 3.12 has AsyncMock. Let's just import AsyncMock.

content = content.replace("from unittest.mock import MagicMock, patch", "from unittest.mock import MagicMock, AsyncMock, patch")

old_mock_post = """    async def mock_post(*args, **kwargs):
        return mock_resp

    mock_client.post = mock_post"""

new_mock_post = """    mock_client.post = AsyncMock(return_value=mock_resp)"""

content = content.replace(old_mock_post, new_mock_post)

with open("tests/test_phase6_mime_and_ipc.py", "w") as f:
    f.write(content)
