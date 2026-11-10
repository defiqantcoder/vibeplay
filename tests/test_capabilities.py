import sys
from pathlib import Path
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


def test_check_essentia_capability_missing_models(tmp_path: Path):
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        status = check_essentia_capability(models_dir)
        assert status.available is False
        assert "no .pb model weights" in status.detail
        assert "Download required .pb models" in str(status.remediation)


def test_check_essentia_capability_with_models(tmp_path: Path):
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "model.pb").touch()
        status = check_essentia_capability(models_dir)
        assert status.available is True
        assert status.provider == "EssentiaAnalyzer"


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
        assert "acoustid-python" in str(status.remediation)


def test_check_acoustid_capability_missing_fpcalc():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = None
        status = check_acoustid_capability(api_key="secret")
        assert status.available is False
        assert "sudo apt install libchromaprint-tools" in str(status.remediation)


def test_check_acoustid_capability_missing_api_key():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which, patch("os.getenv", return_value=None):
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = "/usr/bin/fpcalc"
        status = check_acoustid_capability(api_key=None)
        assert status.available is False
        assert "VIBEPLAY_ACOUSTID_API_KEY" in str(status.remediation)


def test_check_llm_capability_gemini_success(mock_settings: Settings):
    status = check_llm_capability(mock_settings)
    assert status.available is True
    assert status.provider == "Google Gemini"


def test_check_llm_capability_gemini_missing_key(mock_settings: Settings):
    mock_settings.gemini_api_key = ""
    status = check_llm_capability(mock_settings)
    assert status.available is False
    assert "Rule Parser" in status.provider


def test_check_llm_capability_ollama_success(mock_settings: Settings):
    mock_settings.llm_provider = "ollama"
    mock_settings.ollama_base_url = "http://localhost:11434"
    status = check_llm_capability(mock_settings)
    assert status.available is True
    assert status.provider == "Ollama (Local)"


def test_check_llm_capability_ollama_missing_endpoint(mock_settings: Settings):
    mock_settings.llm_provider = "ollama"
    mock_settings.ollama_base_url = ""
    status = check_llm_capability(mock_settings)
    assert status.available is False


def test_check_llm_capability_invalid_provider(mock_settings: Settings):
    mock_settings.llm_provider = "invalid_provider"
    status = check_llm_capability(mock_settings)
    assert status.available is False
    assert "Unknown LLM provider" in status.detail


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
        assert "python-mpd2" in str(status.remediation)


def test_check_mpd_capability_missing_bin():
    with patch("importlib.util.find_spec") as mock_find_spec, patch("shutil.which") as mock_which:
        mock_find_spec.return_value = MagicMock()
        mock_which.return_value = None
        status = check_mpd_capability()
        assert status.available is False
        assert "sudo apt install mpd" in str(status.remediation)


def test_check_desktop_gui_capability_success():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()

        # We need to mock gi.require_version and gi.repository
        mock_gi = MagicMock()
        mock_gi.require_version.return_value = None
        mock_gi_repo = MagicMock()
        with patch.dict(sys.modules, {"gi": mock_gi, "gi.repository": mock_gi_repo}):
            status = check_desktop_gui_capability()
            assert status.available is True


def test_check_desktop_gui_capability_missing_webview():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = None
        status = check_desktop_gui_capability()
        assert status.available is False
        assert "pywebview" in str(status.remediation)


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
            assert "sudo apt install gir1.2-gtk-3.0 gir1.2-webkit2-4.1" in str(status.remediation)


def test_check_desktop_gui_capability_value_error():
    with patch("importlib.util.find_spec") as mock_find_spec:
        mock_find_spec.return_value = MagicMock()

        mock_gi = MagicMock()
        mock_gi.require_version.side_effect = ValueError("mock ValueError")
        with patch.dict(sys.modules, {"gi": mock_gi}):
            status = check_desktop_gui_capability()
            assert status.available is False
            assert "bindings not found" in status.detail


@patch("vibeplay.capabilities.check_essentia_capability")
@patch("vibeplay.capabilities.check_acoustid_capability")
@patch("vibeplay.capabilities.check_llm_capability")
@patch("vibeplay.capabilities.check_mpd_capability")
@patch("vibeplay.capabilities.check_desktop_gui_capability")
def test_check_all_capabilities(mock_desktop, mock_mpd, mock_llm, mock_acoustid, mock_essentia, mock_settings: Settings):
    mock_essentia.return_value = CapabilityStatus("Audio Analysis", True, "Provider", "Detail")
    mock_acoustid.return_value = CapabilityStatus("AcoustID", True, "Provider", "Detail")
    mock_llm.return_value = CapabilityStatus("LLM", True, "Provider", "Detail")
    mock_mpd.return_value = CapabilityStatus("MPD", True, "Provider", "Detail")
    mock_desktop.return_value = CapabilityStatus("Desktop GUI", True, "Provider", "Detail")

    caps = check_all_capabilities(mock_settings)
    assert len(caps) == 5
    for cap in caps:
        assert isinstance(cap, CapabilityStatus)

    mock_essentia.assert_called_once()
    mock_acoustid.assert_called_once()
    mock_llm.assert_called_once()
    mock_mpd.assert_called_once()
    mock_desktop.assert_called_once()
