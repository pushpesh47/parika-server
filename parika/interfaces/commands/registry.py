"""
PARIKA Interfaces - Command Registry

Parses slash-command input and dispatches it to a registered handler.
"""

from __future__ import annotations

from parika.interfaces.errors import UnknownCommandError
from parika.interfaces.formatting.error_formatter import format_exception
from parika.interfaces.session import InterfaceSession

from .base import CommandResult, CommandSpec

COMMAND_PREFIX = "/"


class CommandRegistry:
    """
    Registry of slash commands available to an Interface session.
    """

    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        """
        Register a slash command.

        Raises:
            ValueError:
                If a command with the same name is already
                registered.
        """

        if spec.name in self._commands:
            raise ValueError(
                f"Command '/{spec.name}' is already registered."
            )

        self._commands[spec.name] = spec

    def list_specs(self) -> tuple[CommandSpec, ...]:
        """
        Return every registered command, sorted by name.
        """

        return tuple(
            self._commands[name] for name in sorted(self._commands)
        )

    def is_command(self, line: str) -> bool:
        """
        Determine whether `line` looks like a slash command.
        """

        return line.strip().startswith(COMMAND_PREFIX)

    def dispatch(
        self,
        line: str,
        session: InterfaceSession,
    ) -> CommandResult:
        """
        Parse and execute a slash command line.

        Args:
            line:
                Raw input line, expected to start with `/`.

            session:
                Session the command executes against.

        Returns:
            The command's result. Execution failures are captured
            into a `CommandResult` rather than raised, so an
            Interface REPL never crashes on a bad command.

        Raises:
            UnknownCommandError:
                If `line` does not match any registered command.
        """

        stripped = line.strip()[len(COMMAND_PREFIX):]
        name, _, args = stripped.partition(" ")
        name = name.strip().lower()

        spec = self._commands.get(name)

        if spec is None:
            raise UnknownCommandError(
                f"Unknown command '/{name}'. Type /help to list "
                "available commands."
            )

        try:
            return spec.handler(session, args.strip())

        except Exception as ex:  # noqa: BLE001 - surfaced to the user
            return CommandResult(text=format_exception(ex))
