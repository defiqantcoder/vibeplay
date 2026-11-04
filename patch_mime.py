import re

with open("src/vibeplay/desktop/mime.py", "r") as f:
    content = f.read()

# Add httpx
content = content.replace("from urllib.request import urlopen", "import httpx")
content = content.replace("from urllib.request import Request as UrlRequest\n", "")

# Rewrite function
old_func = """def forward_uris_to_running_instance(
    uris: list[str],
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    timeout: float = 1.5,
    ipc_state_path: Path | None = None,
) -> bool:
    \"\"\"Forward file/URI arguments to an already-running local VibePlay instance.

    Enforces loopback host validation before opening any HTTP connection.

    Returns:
        bool: True if the running instance accepted the payload, False if unreachable.
    \"\"\"
    if not uris:
        return False

    safe_host = validate_loopback_host(host)
    effective_port = port
    effective_token = token

    if effective_token is None:
        ipc_state = read_ipc_state(ipc_state_path)
        if ipc_state:
            state_token = ipc_state.get("token")
            if isinstance(state_token, str) and state_token:
                effective_token = state_token
            state_port = ipc_state.get("port")
            if isinstance(state_port, int) and port == 8765:
                effective_port = state_port

    url_host = f"[{safe_host}]" if ":" in safe_host else safe_host
    url = f"http://{url_host}:{effective_port}/api/desktop/open"
    body = json.dumps({"uris": list(uris)}).encode("utf-8")
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if effective_token:
        headers["X-API-Key"] = effective_token

    req = UrlRequest(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return int(resp.status) == 200
    except (URLError, OSError, ValueError) as err:
        logger.debug(
            "No running instance responded on %s:%d (%s)",
            safe_host,
            effective_port,
            err,
        )
        return False"""

new_func = """async def forward_uris_to_running_instance(
    uris: list[str],
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    timeout: float = 1.5,
    ipc_state_path: Path | None = None,
) -> bool:
    \"\"\"Forward file/URI arguments to an already-running local VibePlay instance.

    Enforces loopback host validation before opening any HTTP connection.
    Executes asynchronously to prevent blocking the event loop.

    Returns:
        bool: True if the running instance accepted the payload, False if unreachable.
    \"\"\"
    if not uris:
        return False

    safe_host = validate_loopback_host(host)
    effective_port = port
    effective_token = token

    if effective_token is None:
        ipc_state = read_ipc_state(ipc_state_path)
        if ipc_state:
            state_token = ipc_state.get("token")
            if isinstance(state_token, str) and state_token:
                effective_token = state_token
            state_port = ipc_state.get("port")
            if isinstance(state_port, int) and port == 8765:
                effective_port = state_port

    url_host = f"[{safe_host}]" if ":" in safe_host else safe_host
    url = f"http://{url_host}:{effective_port}/api/desktop/open"
    body = {"uris": list(uris)}
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if effective_token:
        headers["X-API-Key"] = effective_token

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            return resp.status_code == 200
    except (httpx.RequestError, ValueError) as err:
        logger.debug(
            "No running instance responded on %s:%d (%s)",
            safe_host,
            effective_port,
            err,
        )
        return False"""

content = content.replace(old_func, new_func)

with open("src/vibeplay/desktop/mime.py", "w") as f:
    f.write(content)
