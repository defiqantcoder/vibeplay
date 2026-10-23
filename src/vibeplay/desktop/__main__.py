"""Desktop entry point for running vibeplay as a supervised desktop application."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys
from pathlib import Path

from vibeplay.desktop.constants import DEFAULT_BACKEND_HOST, DEFAULT_BACKEND_PORT
from vibeplay.desktop.supervisor import DesktopSupervisor

logger = logging.getLogger("vibeplay.desktop")


def main(argv: list[str] | None = None) -> int:
    """Parse command line arguments and launch the unified desktop supervisor.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:]).

    Returns:
        int: Exit status code (0 for success).
    """
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(
        prog="vibeplay-desktop",
        description="Unified vibeplay desktop music player shell and runtime supervisor.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_BACKEND_HOST,
        help=f"Host loopback address for backend server (default: {DEFAULT_BACKEND_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_BACKEND_PORT,
        help=f"TCP port for backend server (default: {DEFAULT_BACKEND_PORT})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run backend server and MPD supervisor without launching a PyWebView window",
    )
    parser.add_argument(
        "--no-mpd",
        action="store_true",
        help="Skip starting or attaching to an MPD daemon",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="vibeplay-desktop 0.1.0",
    )
    parser.add_argument(
        "--release-gate",
        action="store_true",
        help="Run automated Phase 7 release gate validation checks and exit",
    )
    parser.add_argument(
        "uris",
        nargs="*",
        help="Optional audio files, playlists (.m3u/.m3u8), or directories passed via desktop launcher (%%U)",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.release_gate:
        import tempfile
        from vibeplay.desktop.release_gate import run_release_gate_checks

        print("VibePlay Phase 7 Release Gate Validation:")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_p = Path(tmp_dir)
            report = run_release_gate_checks(
                db_path=args.db or (tmp_p / "gate.db"),
                settings_path=tmp_p / "desktop_settings.json",
            )
        for check in report.checks:
            tag = "PASS" if check.passed else "FAIL"
            print(f"[{tag}] {check.name}: {check.detail}")
        return 0 if report.passed else 1

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.uris:
        from vibeplay.desktop.mime import forward_uris_to_running_instance

        if forward_uris_to_running_instance(
            args.uris, host=args.host, port=args.port
        ):
            logger.info(
                "Forwarded %d file/URI target(s) to existing instance on %s:%d.",
                len(args.uris),
                args.host,
                args.port,
            )
            return 0

    supervisor = DesktopSupervisor(
        db_path=args.db,
        host=args.host,
        port=args.port,
        start_mpd_child=not args.no_mpd,
        initial_uris=args.uris or None,
    )

    try:
        supervisor.start(headless=args.headless)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user; stopping supervisor.")
        supervisor.stop()
        return 0
    except Exception as err:
        logger.critical("Fatal error running desktop supervisor: %s", err, exc_info=args.debug)
        supervisor.stop()
        return 1


if __name__ == "__main__":
    sys.exit(main())
