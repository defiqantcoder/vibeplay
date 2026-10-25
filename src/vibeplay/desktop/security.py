from __future__ import annotations

import ipaddress


def is_loopback_host(host: str) -> bool:
    """Check if the provided host address is strictly a loopback address."""
    if not host or not isinstance(host, str):
        return False
    normalized = host.strip().lower()
    if normalized in ("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"):
        return True
    if normalized.startswith("127."):
        try:
            addr = ipaddress.ip_address(normalized.strip("[]"))
            return addr.is_loopback
        except ValueError:
            return False
    try:
        addr = ipaddress.ip_address(normalized.strip("[]"))
        return addr.is_loopback
    except ValueError:
        return False


def validate_loopback_host(host: str) -> str:
    """Validate that a host string is strictly a loopback address (127.x.x.x, localhost, or ::1)."""
    if not host or not isinstance(host, str):
        raise ValueError("Host must be a non-empty loopback address.")
    cleaned = host.strip()
    if is_loopback_host(cleaned):
        if cleaned.lower() == "localhost":
            return "localhost"
        try:
            addr = ipaddress.ip_address(cleaned.strip("[]"))
            return str(addr)
        except ValueError:
            return cleaned  # it could be localhost or something that passed is_loopback_host
    raise ValueError(f"Security guardrail: IPC client only connects to loopback interfaces, got '{host}'")
