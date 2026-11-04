import re

with open("tests/test_phase6_mime_and_ipc.py", "r") as f:
    content = f.read()

# Wait, `async def mock_post` was still there, my string replace probably didn't match.

old_mock_post_search = """    async def mock_post(*args, **kwargs):
        return mock_resp

    mock_client.post = mock_post"""

m = re.search(r"async def mock_post\(\*args, \*\*kwargs\):\s*return mock_resp\s*mock_client\.post = mock_post", content)
if m:
    content = content[:m.start()] + "mock_client.post = AsyncMock(return_value=mock_resp)" + content[m.end():]

with open("tests/test_phase6_mime_and_ipc.py", "w") as f:
    f.write(content)
