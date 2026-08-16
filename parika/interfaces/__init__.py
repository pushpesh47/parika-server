"""
PARIKA Interfaces

Provides a reusable Interface abstraction shared by every in-process
presentation layer, without modifying Brain. Today, the sole concrete
in-process presentation layer is the native PARIKA Console
(`parika.console`, formerly `parika.interfaces.cli`). Future external
clients (Desktop, Web, Android, iOS, Voice, a future CLI client)
communicate exclusively through the REST/WebSocket API layer
(`parika/api/`) rather than through this package -- see
`docs/architecture/PARIKA_Architecture_Specification_v1.0.md` for the
distinction between the Console and future external clients.

The Interface layer contains no business logic. It owns:

- Session lifecycle (`session.InterfaceSession`).
- Request parsing (`chat_capability.build_chat_goal`).
- Command parsing and dispatch (`commands`).
- Output formatting (`formatting`).
- Response and error rendering (delegated to each concrete
  presentation layer, e.g. `parika.console`).

Every concrete presentation layer is constructed against a
`ParikaRuntime` (`runtime.build_default_runtime()`), the reusable,
already-wired handle to the PARIKA Core.
"""

from .errors import CommandExecutionError, InterfaceError, UnknownCommandError
from .history import HistoryEntry, HistoryRole
from .runtime import ParikaRuntime, build_default_runtime, shutdown_runtime
from .session import ChatTurnResult, InterfaceSession

__all__ = [
    "ChatTurnResult",
    "CommandExecutionError",
    "HistoryEntry",
    "HistoryRole",
    "InterfaceError",
    "InterfaceSession",
    "ParikaRuntime",
    "UnknownCommandError",
    "build_default_runtime",
    "shutdown_runtime",
]
