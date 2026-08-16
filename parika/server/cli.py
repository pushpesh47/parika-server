"""
PARIKA Server - CLI Argument Parsing

Parses `python -m parika.server`/`parika-server` command-line flags.
No packaging, installer, or system service is implemented or
required -- this is a thin `argparse` wrapper around `uvicorn.run`.
See `docs/guides/Running.md` section 12.2.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerCliArgs:
    host: str | None = None
    port: int | None = None
    reload: bool = False
    log_level: str = "info"


def parse_server_args(argv: list[str] | None = None) -> ServerCliArgs:
    """
    Parse CLI arguments for the development server entry point.

    `host`/`port` default to `None` here (not the `[api]` config
    defaults) so that `parika/server/__main__.py` can tell "the
    operator explicitly overrode this" apart from "use the
    configured default" -- an explicit CLI flag always wins over
    configuration.
    """

    parser = argparse.ArgumentParser(
        prog="parika-server",
        description="Run the PARIKA Server (development mode).",
    )

    parser.add_argument(
        "--host",
        default=None,
        help="Bind host. Defaults to [api].host from configuration.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port. Defaults to [api].port from configuration.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable Uvicorn auto-reload for development.",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        help="Uvicorn log level (default: info).",
    )

    parsed = parser.parse_args(argv)

    return ServerCliArgs(
        host=parsed.host,
        port=parsed.port,
        reload=parsed.reload,
        log_level=parsed.log_level,
    )
