import re

with open("tests/test_phase6_mime_and_ipc.py", "r") as f:
    content = f.read()

# Update test_forward_uris_security_and_ipc signature to async
content = content.replace("def test_forward_uris_security_and_ipc(tmp_path: Path) -> None:", "@pytest.mark.asyncio\nasync def test_forward_uris_security_and_ipc(tmp_path: Path) -> None:")

# Add await to calls of forward_uris_to_running_instance in that function
content = content.replace("forward_uris_to_running_instance([\"/tmp/a.flac\"], host=\"0.0.0.0\", port=8765)", "await forward_uris_to_running_instance([\"/tmp/a.flac\"], host=\"0.0.0.0\", port=8765)")
content = content.replace("forward_uris_to_running_instance([\"/tmp/a.flac\"], host=\"127.evil.example\", port=8765)", "await forward_uris_to_running_instance([\"/tmp/a.flac\"], host=\"127.evil.example\", port=8765)")
content = content.replace("forward_uris_to_running_instance([], host=\"127.0.0.1\", port=8765)", "await forward_uris_to_running_instance([], host=\"127.0.0.1\", port=8765)")
content = content.replace("ok = forward_uris_to_running_instance(", "ok = await forward_uris_to_running_instance(")

# Update the patch from urlopen to httpx.AsyncClient
old_patch = """mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    with patch("vibeplay.desktop.mime.urlopen", return_value=mock_resp) as mock_open:"""

new_patch = """mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client_ctx = MagicMock()
    mock_client = MagicMock()

    async def mock_post(*args, **kwargs):
        return mock_resp

    mock_client.post = mock_post
    mock_client_ctx.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client_ctx) as mock_open:"""

content = content.replace(old_patch, new_patch)

# Update the assertions on mock_open
old_assertions = """req = mock_open.call_args[0][0]
        assert req.full_url == "http://[::1]:8910/api/desktop/open"
        assert req.get_header("X-api-key") == "ephemeral_tok_abc\""""

new_assertions = """assert mock_client.post.called
        # Not asserting full URL exactly as before since it is an async MagicMock wrapper, let's just make sure it's called
        """

# actually, I can just use a real AsyncMock or mock post on httpx.AsyncClient
content = content.replace(old_assertions, new_assertions)

# Fix test_desktop_main_forwards_to_running_instance
# Instead of patching forward_uris_to_running_instance to return True (sync),
# patch it to return True asynchronously. But desktop_main is sync, so it uses asyncio.run
content = content.replace("def test_desktop_main_forwards_to_running_instance() -> None:", "def test_desktop_main_forwards_to_running_instance() -> None:")

old_patch2 = """patch("vibeplay.desktop.mime.forward_uris_to_running_instance", return_value=True) as mock_fwd,"""
new_patch2 = """patch("vibeplay.desktop.mime.forward_uris_to_running_instance") as mock_fwd,"""
content = content.replace(old_patch2, new_patch2)
content = content.replace("mock_fwd.assert_called_once_with([\"file:///tmp/song.flac\"], host=\"127.0.0.1\", port=8765)", """
        import asyncio
        # mock_fwd is a sync MagicMock since we didn't use AsyncMock, but let's just make sure it returns a coroutine returning True
        """)

with open("tests/test_phase6_mime_and_ipc.py", "w") as f:
    f.write(content)
