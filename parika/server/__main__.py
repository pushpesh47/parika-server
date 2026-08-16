"""
PARIKA Server - Entry Point

`python -m parika.server` / the `parika-server` console script.

Development mode only, as mandated: no installer, no system service,
no packaging, no Docker image. Stopping the process stops PARIKA;
restarting the process restarts PARIKA. See `docs/guides/Running.md`
section 12.2.
"""

from __future__ import annotations

import uvicorn

from parika.core.configuration.configuration import Configuration

from .cli import parse_server_args
from .config import load_server_settings


def main(argv: list[str] | None = None) -> int:
    """
    Entry point for `python -m parika.server` and the `parika-server`
    console script.
    """

    args = parse_server_args(argv)

    configuration = Configuration()
    configuration.load()
    settings = load_server_settings(configuration)

    host = args.host if args.host is not None else settings.host
    port = args.port if args.port is not None else settings.port

    uvicorn.run(
        "parika.server.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=args.reload,
        log_level=args.log_level,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
