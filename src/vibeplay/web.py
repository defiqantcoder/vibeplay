"""Local web UI and API server module using FastAPI."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_server(
    db_path: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Start the local vibeplay web server.

    Args:
        db_path: Path to the SQLite database.
        host: Host address to bind to.
        port: Port number to bind to.
    """
    logger.info(
        "Starting web server at http://%s:%d with database %s", host, port, db_path
    )
    raise NotImplementedError("Web server will be implemented in Phase 7.")
