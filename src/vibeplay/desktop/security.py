"""Desktop security guardrails: canonical loopback host validation and file permissions."""

from __future__ import annotations

import ipaddress
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Canonical set of string host aliases recognized as loopback
LOOPBACK_STRING_ALIASES: frozenset[str] = frozenset(
    {
        "localhost",
        "ip6-localhost",
        "ip6-loopback",
    }
)


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
        raise ValueError(f"Security Guardrail: Desktop host must be a loopback address (Security guardrail invariant violated: got '{host}')")
    return host.strip()


_SYSTEM_MEDIA_ROOTS: tuple[str, ...] = ("/media", "/mnt", "/run/media", "/music")


def allowed_media_roots(*extra: Path | str | None) -> list[Path]:
    """Return resolved directories under which user-supplied media paths are permitted.

    Includes the user's home directory, standard removable-media mount points,
    and any extra roots (e.g. the configured music directory).
    """
    roots: list[Path] = [Path.home().resolve()]
    roots.extend(Path(r) for r in _SYSTEM_MEDIA_ROOTS)
    for item in extra:
        if item:
            roots.append(Path(item).expanduser().resolve())

    for item in os.environ.get("VIBEPLAY_EXTRA_MEDIA_ROOTS", "").split(os.pathsep):
        if item.strip():
            roots.append(Path(item).expanduser().resolve())
    return roots


class PathTraversalError(PermissionError, ValueError):
    """Raised when a path escapes permitted boundaries or contains malicious sequences."""

    pass


def resolve_within(path: Path | str, roots: list[Path] | tuple[Path, ...]) -> Path:
    """Resolve ``path`` (following symlinks) and require it to live inside one of ``roots``.

    Raises:
        PathTraversalError: If the path contains NUL bytes or escapes every allowed root.
    """
    raw = str(path)
    if "\x00" in raw:
        raise PathTraversalError("Path contains invalid characters.")
    if not raw.strip():
        raise PathTraversalError("Path cannot be empty.")
    target_p = Path(raw).expanduser()
    for root in roots:
        base_dir = Path(root).resolve()
        try:
            if target_p.is_absolute():
                resolved_path = target_p.resolve()
            else:
                resolved_path = (base_dir / target_p).resolve()
            if resolved_path.is_relative_to(base_dir):
                return resolved_path
        except (ValueError, RuntimeError, OSError):
            continue
    raise PathTraversalError("Path traversal attempt detected: path is outside permitted directories.")


def secure_chmod(path_or_fd: int | Path | str, mode: int = 0o600) -> None:
    """Apply permissions to a file descriptor or an existing file path.

    Paths outside ~/.config/vibeplay raise ValueError unless PYTEST_CURRENT_TEST
    is set. File descriptors bypass this path check; OS permission errors propagate.
    """
    if isinstance(path_or_fd, int):
        os.fchmod(path_or_fd, mode)
    else:
        base = Path("~/.config/vibeplay").expanduser().resolve()
        p = Path(path_or_fd).expanduser().resolve()
        if not p.is_relative_to(base) and "PYTEST_CURRENT_TEST" not in os.environ:
            raise ValueError("Path traversal attempt detected")
        if p.exists():
            os.chmod(p, mode)


def ensure_secure_directory(dir_path: Path | str, mode: int = 0o700) -> Path:
    """Create and return a resolved directory, attempting to set its permissions.

    Paths outside ~/.config/vibeplay raise ValueError unless PYTEST_CURRENT_TEST
    is set. Directory creation errors propagate; chmod errors are ignored. The
    default mode is 0o700.
    """
    base = Path("~/.config/vibeplay").expanduser().resolve()
    p = Path(dir_path).expanduser().resolve()
    if not p.is_relative_to(base) and "PYTEST_CURRENT_TEST" not in os.environ:
        raise ValueError("Path traversal attempt detected")
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, mode)
    except OSError as err:
        logger.debug("Could not chmod directory %s to %o: %s", p, mode, err)
    return p
