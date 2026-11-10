"""API Routers for vibeplay modular endpoint routing."""

from vibeplay.routers.player import router as player_router
from vibeplay.routers.root import router as root_router
from vibeplay.routers.settings import router as settings_router

__all__ = ["settings_router", "player_router", "root_router"]
