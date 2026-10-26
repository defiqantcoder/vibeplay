"""Desktop security guardrails: canonical loopback host validation and file permissions."""

from __future__ import annotations

import ipaddress
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Canonical set of string host aliases recognized as loopback
LOOPBACK_STRING_ALIASES: frozenset[str] = frozenset({
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
})


def is_loopback_host(host: str | None) -> bool:
    """Return True if host is strictly a loopback address or alias, False otherwise.

    Accepts IPv4 loopback (127.0.0.0/8), IPv6 loopback (::1, [::1]), and
    canonical localhost names. Rejects all external, wildcard (0.0.0.0, ::),
    and broadcast addresses.
    """
    if not host or not isinstance(host, str):
        return False

    cleaned = host.strip().lower()
    if not cleaned:
        return False

    if cleaned in LOOPBACK_STRING_ALIASES:
        return True

    # Strip bracketed IPv6 notation e.g. "[::1]"
    ip_candidate = cleaned[1:-1] if cleaned.startswith("[") and cleaned.endswith("]") else cleaned

    try:
        addr = ipaddress.ip_address(ip_candidate)
        return addr.is_loopback
    except ValueError:
        return False


def validate_loopback_host(host: str) -> str:
    """Validate that host is strictly a loopback address, returning normalized host string.

    Raises:
        ValueError: If host is not a valid loopback address.
    """
    if not is_loopback_host(host):
        raise ValueError(
            f"Security Guardrail: Desktop host must be a loopback address (Security guardrail invariant violated: got '{host}')"
        )
    return host.strip()


def secure_chmod(path_or_fd: int | Path | str, mode: int = 0o600) -> None:
    """Apply restrictive permissions to a file path or file descriptor."""
    if isinstance(path_or_fd, int):
        os.fchmod(path_or_fd, mode)
    else:
        p = Path(path_or_fd).expanduser().resolve()
        if p.exists():
            os.chmod(p, mode)


def ensure_secure_directory(dir_path: Path | str, mode: int = 0o700) -> Path:
    """Ensure directory exists and has locked-down owner-only permissions (0o700)."""
    p = Path(dir_path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, mode)
    except OSError as err:
        logger.debug("Could not chmod directory %s to %o: %s", p, mode, err)
    return p
