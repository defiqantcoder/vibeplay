"""Tests for vibeplay configuration module."""

import os
from unittest import mock

from vibeplay.config import get_settings


def test_get_settings_loads_from_env() -> None:
    """Verify that get_settings correctly loads configuration from environment variables."""
    # Ensure cache is clear before testing
    get_settings.cache_clear()

    # Define environment variables to patch
    env_vars = {
        "VIBEPLAY_ENV": "testing_env",
        "LOG_LEVEL": "DEBUG",
    }

    # Patch os.environ and verify settings
    with mock.patch.dict(os.environ, env_vars, clear=False):
        settings = get_settings()
        assert settings.vibeplay_env == "testing_env"
        assert settings.log_level == "DEBUG"

    # Clear cache again so other tests are not affected
    get_settings.cache_clear()
