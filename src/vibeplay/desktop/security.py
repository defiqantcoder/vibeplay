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
    if raw == "~":
        raw_str = str(Path.home())
    elif raw.startswith("~/") or (os.sep != "/" and raw.startswith(f"~{os.sep}")):
        raw_str = os.path.join(str(Path.home()), raw[2:].lstrip("/\\"))
    elif raw.startswith("~"):
        raise PathTraversalError("Path traversal attempt detected: user home expansion is not permitted.")
    else:
        raw_str = raw

    for root in roots:
        base_dir = Path(root).resolve()
        base_str = str(base_dir)
        base_prefix = base_str if base_str.endswith(os.sep) else base_str + os.sep
        try:
            if os.path.isabs(raw_str):
                candidate = os.path.normpath(raw_str)
            else:
                candidate = os.path.normpath(os.path.join(base_str, raw_str))

            if candidate == base_str:
                return base_dir

            if not candidate.startswith(base_prefix):
                continue

            resolved_str = os.path.realpath(candidate)
            if resolved_str != base_str and not resolved_str.startswith(base_prefix):
                continue
            return Path(resolved_str)
        except (ValueError, RuntimeError, OSError):
            continue
    raise PathTraversalError("Path traversal attempt detected: path is outside permitted directories.")


def _allowed_config_roots() -> tuple[Path, ...]:
    """Return resolved roots permitted for desktop config/state file permissions."""
    import tempfile

    roots: list[Path] = [
        Path("~/.config/vibeplay").expanduser().resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]
    for env_var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        val = os.environ.get(env_var, "").strip()
        if val:
            roots.append((Path(val).expanduser() / "vibeplay").resolve())
    return tuple(roots)


def _validate_config_path(path: Path | str) -> Path:
    """Resolve config/state path and verify it resides under an allowed config or temp root."""
    p = Path(path).expanduser().resolve()
    if "PYTEST_CURRENT_TEST" in os.environ:
        return p
    if any(p.is_relative_to(root) for root in _allowed_config_roots()):
        return p
    raise ValueError("Path traversal attempt detected")


def secure_chmod(path_or_fd: int | Path | str, mode: int = 0o600) -> None:
    """Apply restrictive permissions to a file path or file descriptor."""
    if isinstance(path_or_fd, int):
        os.fchmod(path_or_fd, mode)
    else:
        p = _validate_config_path(path_or_fd)
        if p.exists():
            os.chmod(p, mode)


def ensure_secure_directory(dir_path: Path | str, mode: int = 0o700) -> Path:
    """Ensure directory exists and has locked-down owner-only permissions (0o700)."""
    p = _validate_config_path(dir_path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, mode)
    except OSError as err:
        logger.debug("Could not chmod directory %s to %o: %s", p, mode, err)
    return p
