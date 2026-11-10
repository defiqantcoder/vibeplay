"""vibeplay: Local music library scanner, metadata enricher, and vibe-based smart playlist generator."""

import warnings

warnings.filterwarnings("ignore", message=".*StarletteDeprecationWarning.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="starlette.*")

__version__ = "2.0.2"
__all__ = ["__version__"]
