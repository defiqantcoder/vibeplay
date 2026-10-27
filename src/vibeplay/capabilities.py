import importlib
import importlib.util
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from vibeplay.config import Settings


@dataclass(frozen=True)
class CapabilityStatus:
    name: str
    available: bool
    provider: str
    detail: str
    remediation: str | None = None


def check_essentia_capability(models_dir: Path | None = None) -> CapabilityStatus:
    essentia_spec = importlib.util.find_spec("essentia")
    if essentia_spec is None:
        return CapabilityStatus(
            name="Audio Analysis (Essentia)",
            available=False,
            provider="LibrosaAnalyzer (Fallback)",
            detail="Essentia not found, using Librosa fallback.",
            remediation="pip install essentia or install via system package manager.",
        )

    # We could also check models_dir for .pb files if provided,
    # but for now we consider essentia available if importable.
    if models_dir is not None and models_dir.exists():
        pb_files = list(models_dir.glob("*.pb"))
        if not pb_files:
            return CapabilityStatus(
                name="Audio Analysis (Essentia Models)",
                available=False,
                provider="LibrosaAnalyzer (Fallback)",
                detail="Essentia found but no .pb model weights present in models_dir.",
                remediation=f"Download required .pb models to {models_dir}",
            )

    return CapabilityStatus(
        name="Audio Analysis",
        available=True,
        provider="EssentiaAnalyzer",
        detail="Essentia library and models available.",
    )


def check_acoustid_capability(api_key: str | None = None) -> CapabilityStatus:
    acoustid_spec = importlib.util.find_spec("acoustid")
    fpcalc_path = shutil.which("fpcalc")

    # Check env var if api_key not provided
    key = api_key or os.getenv("VIBEPLAY_ACOUSTID_API_KEY")

    if acoustid_spec is None:
        return CapabilityStatus(
            name="AcoustID Fingerprinting",
            available=False,
            provider="None",
            detail="acoustid-python package not found.",
            remediation="pip install acoustid-python",
        )

    if not fpcalc_path:
        return CapabilityStatus(
            name="AcoustID Fingerprinting",
            available=False,
            provider="None",
            detail="fpcalc binary not found on PATH.",
            remediation="sudo apt install libchromaprint-tools",
        )

    if not key:
        return CapabilityStatus(
            name="AcoustID Fingerprinting",
            available=False,
            provider="None",
            detail="VIBEPLAY_ACOUSTID_API_KEY not configured.",
            remediation="Set VIBEPLAY_ACOUSTID_API_KEY in environment or config.",
        )

    return CapabilityStatus(
        name="AcoustID Fingerprinting",
        available=True,
        provider="AcoustID",
        detail="fpcalc binary and API key present.",
    )


def check_llm_capability(settings: Settings) -> CapabilityStatus:
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            return CapabilityStatus(
                name="LLM Vibe Analysis",
                available=False,
                provider="Deterministic Rule Parser (Fallback)",
                detail="Gemini provider selected but API key missing.",
                remediation="Set VIBEPLAY_GEMINI_API_KEY in environment or config.",
            )
        return CapabilityStatus(
            name="LLM Vibe Analysis",
            available=True,
            provider="Google Gemini",
            detail="Gemini API key configured.",
        )
    elif settings.llm_provider == "ollama":
        if not settings.ollama_base_url:
            return CapabilityStatus(
                name="LLM Vibe Analysis",
                available=False,
                provider="Deterministic Rule Parser (Fallback)",
                detail="Ollama provider selected but endpoint missing.",
                remediation="Set VIBEPLAY_OLLAMA_ENDPOINT in environment or config.",
            )
        return CapabilityStatus(
            name="LLM Vibe Analysis",
            available=True,
            provider="Ollama (Local)",
            detail=f"Ollama configured at {settings.ollama_base_url}.",
        )

    return CapabilityStatus(
        name="LLM Vibe Analysis",
        available=False,
        provider="Deterministic Rule Parser (Fallback)",
        detail=f"Unknown LLM provider: {settings.llm_provider}",
        remediation="Configure llm_provider to 'gemini' or 'ollama'.",
    )


def check_mpd_capability() -> CapabilityStatus:
    mpd_spec = importlib.util.find_spec("mpd")
    mpd_bin = shutil.which("mpd")

    if mpd_spec is None:
        return CapabilityStatus(
            name="MPD Playback",
            available=False,
            provider="None",
            detail="python-mpd2 package not found.",
            remediation="pip install python-mpd2",
        )

    if not mpd_bin:
        return CapabilityStatus(
            name="MPD Playback",
            available=False,
            provider="None",
            detail="mpd binary not found.",
            remediation="sudo apt install mpd",
        )

    return CapabilityStatus(
        name="MPD Playback",
        available=True,
        provider="MPD",
        detail="MPD daemon and python client available.",
    )


def check_desktop_gui_capability() -> CapabilityStatus:
    webview_spec = importlib.util.find_spec("webview")
    if webview_spec is None:
        return CapabilityStatus(
            name="Desktop GUI",
            available=False,
            provider="None",
            detail="pywebview package not found.",
            remediation="pip install pywebview",
        )

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        # Try importing to ensure they actually exist after require_version
        from gi.repository import Gtk, WebKit2  # noqa: F401
    except (ImportError, ValueError) as e:
        return CapabilityStatus(
            name="Desktop GUI",
            available=False,
            provider="None",
            detail=f"GTK3 or WebKit2 introspection bindings not found: {e}",
            remediation="sudo apt install gir1.2-gtk-3.0 gir1.2-webkit2-4.1",
        )

    return CapabilityStatus(
        name="Desktop GUI",
        available=True,
        provider="pywebview (GTK)",
        detail="Pywebview and GTK/WebKit dependencies met.",
    )


def check_all_capabilities(settings: Settings | None = None) -> list[CapabilityStatus]:
    if settings is None:
        # Fallback to loading default settings if none provided
        from vibeplay.config import get_settings

        settings = get_settings()

    return [
        check_essentia_capability(settings.essentia_models_dir if hasattr(settings, "essentia_models_dir") else None),
        check_acoustid_capability(settings.acoustid_api_key if hasattr(settings, "acoustid_api_key") else None),
        check_llm_capability(settings),
        check_mpd_capability(),
        check_desktop_gui_capability(),
    ]
