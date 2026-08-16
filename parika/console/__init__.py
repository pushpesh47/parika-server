"""
PARIKA Console.

PARIKA's native administration console: an interactive command-line
REPL bundled with the server, communicating directly with PARIKA Core
exactly like this package always has. It is not an external client
and is not restricted by, or routed through, the REST/WebSocket API
layer (`parika/api/`) -- see `docs/architecture/PARIKA_Architecture_Specification_v1.0.md`
for the distinction between the native Console and future external
clients (Desktop, Web, Android, iOS, Voice, a future CLI client),
which will communicate exclusively through `/api/v1`.

Entry points: `parika` or `python -m parika` (both resolve to
`main()` in `app.py`).
"""

from .app import CliApplication, main

__all__ = [
    "CliApplication",
    "main",
]
