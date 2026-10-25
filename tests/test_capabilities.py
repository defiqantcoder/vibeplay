import sys
from unittest.mock import MagicMock, patch

import pytest

from vibeplay.capabilities import (
    CapabilityStatus,
    check_acoustid_capability,
    check_all_capabilities,
    check_desktop_gui_capability,
    check_essentia_capability,
    check_llm_capability,
    check_mpd_capability,
)
from vibeplay.config import Settings


@pytest.fixture
def mock_settings():
    return Settings(sqlite_db_path=":memory:", music_library_path="/tmp", llm_provider="gemini", gemini_api_key="test_key")


def test_check_essentia_capability_success():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()
        status = check_essentia_capability()
        assert status.available is True
        assert status.provider == "EssentiaAnalyzer"


def test_check_essentia_capability_missing_import():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = None
        status = check_essentia_capability()
        assert status.available is False
        assert "fallback" in status.detail.lower()
        assert "pip install essentia" in status.remediation


def test_check_essentia_capability_missing_models(tmp_path):
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        status = check_essentia_capability(models_dir)
        assert status.available is False
        assert "no .pb model weights" in status.detail
        assert "Download required .pb models" in status.remediation


def test_check_acoustid_capability_success():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = "/usr/bin/fpcalc"
        status = check_acoustid_capability(api_key="secret")
        assert status.available is True
        assert status.provider == "AcoustID"


def test_check_acoustid_capability_missing_import():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = None
        status = check_acoustid_capability(api_key="secret")
        assert status.available is False
        assert "acoustid-python" in status.remediation


def test_check_acoustid_capability_missing_fpcalc():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = None
        status = check_acoustid_capability(api_key="secret")
        assert status.available is False
        assert "sudo apt install libchromaprint-tools" in status.remediation


def test_check_acoustid_capability_missing_api_key():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = "/usr/bin/fpcalc"
        status = check_acoustid_capability(api_key="")
        assert status.available is False
        assert "VIBEPLAY_ACOUSTID_API_KEY" in status.remediation


def test_check_llm_capability_gemini_success(mock_settings):
    status = check_llm_capability(mock_settings)
    assert status.available is True
    assert status.provider == "Google Gemini"


def test_check_llm_capability_gemini_missing_key(mock_settings):
    mock_settings.gemini_api_key = ""
    status = check_llm_capability(mock_settings)
    assert status.available is False
    assert "Rule Parser" in status.provider


def test_check_llm_capability_ollama_success(mock_settings):
    mock_settings.llm_provider = "ollama"
    mock_settings.ollama_base_url = "http://localhost:11434"
    status = check_llm_capability(mock_settings)
    assert status.available is True
    assert status.provider == "Ollama (Local)"


def test_check_llm_capability_ollama_missing_endpoint(mock_settings):
    mock_settings.llm_provider = "ollama"
    mock_settings.ollama_base_url = ""
    status = check_llm_capability(mock_settings)
    assert status.available is False


def test_check_mpd_capability_success():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = "/usr/bin/mpd"
        status = check_mpd_capability()
        assert status.available is True


def test_check_mpd_capability_missing_import():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = None
        mock_which.return_value = "/usr/bin/mpd"
        status = check_mpd_capability()
        assert status.available is False
        assert "python-mpd2" in status.remediation


def test_check_mpd_capability_missing_bin():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = None
        status = check_mpd_capability()
        assert status.available is False
        assert "sudo apt install mpd" in status.remediation


def test_check_desktop_gui_capability_success():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()

        # We need to mock gi.require_version and gi.repository
        mock_gi = MagicMock()
        mock_gi_repo = MagicMock()
        sys.modules["gi"] = mock_gi
        sys.modules["gi.repository"] = mock_gi_repo

        try:
            status = check_desktop_gui_capability()
            assert status.available is True
        finally:
            del sys.modules["gi"]
            del sys.modules["gi.repository"]


def test_check_desktop_gui_capability_missing_webview():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = None
        status = check_desktop_gui_capability()
        assert status.available is False
        assert "pywebview" in status.remediation


def test_check_desktop_gui_capability_missing_gi():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()

        # Make gi import fail
        import builtins

        original_import = builtins.__import__

        def side_effect(name, *args, **kwargs):
            if name == "gi":
                raise ImportError("No module named gi")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=side_effect):
            status = check_desktop_gui_capability()
            assert status.available is False
            assert "sudo apt install gir1.2-gtk-3.0 gir1.2-webkit2-4.1" in status.remediation


def test_check_all_capabilities(mock_settings):
    caps = check_all_capabilities(mock_settings)
    assert len(caps) == 5
    # Just checking they return CapabilityStatus instances
    for cap in caps:
        assert isinstance(cap, CapabilityStatus)
