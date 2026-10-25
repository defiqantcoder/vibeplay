"""Targeted tests for canonical loopback validation and file/directory security permissions."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from vibeplay.desktop.security import (
    ensure_secure_directory,
    is_loopback_host,
    secure_chmod,
    validate_loopback_host,
)


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("127.255.255.254", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("  localhost  ", True),
        ("ip6-localhost", True),
        ("ip6-loopback", True),
        ("::1", True),
        ("[::1]", True),
        ("0.0.0.0", False),
        ("::", False),
        ("[::]", False),
        ("192.168.1.1", False),
        ("10.0.0.1", False),
        ("8.8.8.8", False),
        ("example.com", False),
        ("", False),
        ("   ", False),
        (None, False),
    ],
)
def test_is_loopback_host(host, expected):
    assert is_loopback_host(host) is expected


def test_validate_loopback_host_success():
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    assert validate_loopback_host("  localhost  ") == "localhost"
    assert validate_loopback_host("::1") == "::1"
    assert validate_loopback_host("[::1]") == "[::1]"


def test_validate_loopback_host_rejection():
    with pytest.raises(ValueError, match="Security Guardrail"):
        validate_loopback_host("0.0.0.0")

    with pytest.raises(ValueError, match="Security Guardrail"):
        validate_loopback_host("192.168.0.10")

    with pytest.raises(ValueError, match="Security Guardrail"):
        validate_loopback_host("example.com")


def test_secure_chmod_file_path(tmp_path: Path):
    f = tmp_path / "test_perm.txt"
    f.write_text("hello", encoding="utf-8")
    os.chmod(f, 0o666)
    assert stat.S_IMODE(f.stat().st_mode) != 0o600

    secure_chmod(f, 0o600)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_secure_chmod_file_descriptor(tmp_path: Path):
    f = tmp_path / "test_fd.txt"
    fd = os.open(str(f), os.O_CREAT | os.O_WRONLY, 0o666)
    try:
        secure_chmod(fd, 0o600)
        assert stat.S_IMODE(os.fstat(fd).st_mode) == 0o600
    finally:
        os.close(fd)


def test_ensure_secure_directory(tmp_path: Path):
    target_dir = tmp_path / "secure_sub" / "nested"
    assert not target_dir.exists()

    res = ensure_secure_directory(target_dir, 0o700)
    assert res == target_dir.resolve()
    assert target_dir.is_dir()
    assert stat.S_IMODE(target_dir.stat().st_mode) == 0o700
