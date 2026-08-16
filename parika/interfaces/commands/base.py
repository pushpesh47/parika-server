"""
PARIKA Interfaces - Command Base Types

Defines the small, presentation-neutral types shared by every
built-in slash command.

Slash commands execute entirely inside the Interface layer: they read
from `ParikaRuntime`'s Core managers directly for read-only
introspection (module/provider/tool/capability listings, resource and
health snapshots) but never go through Brain and never mutate Core
state beyond what an explicit, narrow command (`/reload`, `/clear`)
is documented to do.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from parika.interfaces.session import InterfaceSession


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResult:
    """
    Immutable outcome of executing a single slash command.
    """

    text: str
    """
    Text to display to the user.
    """

    should_exit: bool = False
    """
    Whether the Interface should end the session after displaying
    `text`.
    """

    should_clear_screen: bool = False
    """
    Whether the Interface should clear its display after showing
    `text` (typically empty for this case).
    """

    new_session: InterfaceSession | None = None
    """
    When set (e.g. by `/sessions resume <id>`), the Interface should
    replace its active session with this one. None (the default)
    leaves the active session unchanged -- every existing command's
    behavior is completely unaffected by this additive field.
    """


CommandHandler = Callable[[InterfaceSession, str], CommandResult]
"""
A slash command handler: given the active session and the raw
argument text following the command name, produces a CommandResult.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandSpec:
    """
    Immutable registration record for a single slash command.
    """

    name: str
    """
    Command name, without the leading slash (e.g. "help").
    """

    description: str
    """
    Short, human-readable description shown by `/help`.
    """

    handler: CommandHandler
    """
    Callable that executes the command.
    """
