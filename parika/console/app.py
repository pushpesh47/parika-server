"""
PARIKA Console - Application

Implements PARIKA's native, interactive administration console: a
REPL that renders Markdown, streams tokens as they arrive, supports
command history and arrow-key navigation (via the standard library
`readline` module), multiline input, graceful `Ctrl+C`/`Ctrl+D`
handling, and every built-in slash command.

The Console communicates directly with PARIKA Core, in-process,
exactly as this module always has -- it is not an external client of
the REST/WebSocket API layer, is not subject to client authentication
or rate limiting, and is not limited by the shape of any public API
endpoint. See `docs/architecture/PARIKA_Architecture_Specification_v1.0.md`
for the distinction between the Console and future external clients.

This module contains no business logic: normal text is handed to
`InterfaceSession.submit_text()`, which builds a `BrainRequest` and
submits it to Brain; slash commands are dispatched by
`CommandRegistry`, which reads other Core managers directly for
read-only introspection but never calls Brain.
"""

from __future__ import annotations

import argparse
import atexit
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parika.interfaces.commands import CommandRegistry, create_default_registry
from parika.interfaces.history import HistoryRole
from parika.interfaces.runtime import (
    ParikaRuntime,
    build_default_runtime,
    shutdown_runtime,
)
from parika.interfaces.session import InterfaceSession
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module

from .colors import Ansi, colorize
from .markdown import render_markdown
from .progress_view import ConsoleProgressRenderer
from .spinner_view import SpinnerProgressRenderer
from .streaming import StreamingPrinter
from .terminal_title import reset_terminal_title
from .tool_footer import ToolFooterMode, render_tool_footer
from .workspace_permission_prompt import CliWorkspacePermissionPrompt

CLI_VERSION = "0.1.0"

_CLEAR_SCREEN_SEQUENCE = "\033[2J\033[H"
_LINE_CONTINUATION_SUFFIX = "\\"
_CONTINUATION_PROMPT = "... "
_DEFAULT_PROMPT = "\u276f"  # ❯

_TAGLINE = "Personal Adaptive Responsive Intelligence Kernel Assistant"
_READY_MESSAGE = "Ready."
_EXIT_MESSAGE = "Session ended."
_CANCELLED_MESSAGE = "Request cancelled."

ProgressRenderer = ConsoleProgressRenderer | SpinnerProgressRenderer
"""
Either rendering mode the Console can wire up for execution-progress
events: the verbose, one-line-per-event `ConsoleProgressRenderer`
(Debug Mode), or the transient, single-line `SpinnerProgressRenderer`
(Normal Mode, the default). Both expose the same `start()`/`stop()`
lifecycle and differ only in how they render -- never in what
execution events exist or mean.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsoleCliArgs:
    """
    Parsed `parika`/`python -m parika.console` command-line flags.

    `debug` defaults to `None` (not the `interfaces.cli.debug` config
    default) so `main()` can tell "the operator explicitly passed
    `--debug`" apart from "use the configured default" -- an explicit
    CLI flag always wins over configuration.
    """

    debug: bool | None = None


def parse_console_args(argv: list[str] | None = None) -> ConsoleCliArgs:
    """
    Parse CLI arguments for the `parika` console entry point.
    """

    parser = argparse.ArgumentParser(
        prog="parika",
        description="Run the PARIKA interactive console.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help=(
            "Render execution progress verbosely (one line per event) "
            "instead of the default, transient spinner status line. "
            "Overrides interfaces.cli.debug from configuration."
        ),
    )

    parsed = parser.parse_args(argv)

    return ConsoleCliArgs(debug=parsed.debug)


def _default_session_store(runtime: ParikaRuntime) -> PostgreSQLSessionStore:
    """Construct and initialize the default session store using PostgreSQL."""

    configuration = runtime.configuration
    db_config = db_config_module.load_database_config(configuration)
    
    pool = PoolManager.get_sync_pool()
    if pool is None:
        raise RuntimeError("PostgreSQL enabled but sync pool not initialized")
    
    store = PostgreSQLSessionStore(pool)
    store.initialize()
    return store


class CliApplication:
    """
    Interactive PARIKA CLI REPL.
    """

    def __init__(
        self,
        runtime: ParikaRuntime,
        *,
        color: bool = True,
        markdown: bool = True,
        stream: bool = True,
        progress: bool = True,
        debug: bool = False,
        tool_footer_mode: ToolFooterMode = ToolFooterMode.SMART,
        history_file: Path | None = None,
        history_size: int = 1000,
        registry: CommandRegistry | None = None,
        session: InterfaceSession | None = None,
        session_store: PostgreSQLSessionStore | None = None,
    ) -> None:
        """
        Initialize the CLI application.

        Args:
            runtime:
                Already-wired PARIKA runtime.

            color:
                Whether to emit ANSI colors.

            markdown:
                Whether to render Markdown formatting.

            stream:
                Whether to stream chat tokens as they arrive.

            progress:
                Whether to render real execution-progress events
                live while a request is in flight, in either rendering
                mode (see `debug`). Independent of `stream`, which
                only governs the model's own answer text. Has no
                effect when `runtime` exposes no `event_bus` (e.g. a
                minimal test double).

            debug:
                Which rendering mode to use when `progress` is
                enabled. `False` (default, "Normal Mode") renders a
                single, transient spinner status line via
                `spinner_view.SpinnerProgressRenderer`. `True` ("Debug
                Mode") renders the previous, fully verbose, one-line-
                per-event output via
                `progress_view.ConsoleProgressRenderer`, unchanged,
                for developers inspecting execution. Purely a
                rendering choice: has no effect on execution itself.

            tool_footer_mode:
                Which tool-footer rendering mode to use after a chat
                turn's answer -- see `tool_footer.ToolFooterMode` and
                `interfaces.cli.tool_footer_mode`. Purely a rendering
                choice: the same `tool_invocations` data is available
                to this Console regardless of which mode is selected.

            history_file:
                Optional path used to persist input history across
                runs via `readline`.

            history_size:
                Maximum number of lines kept in the `readline` history
                file.

            registry:
                Optional explicit CommandRegistry override, primarily
                for tests.

            session:
                Optional explicit InterfaceSession override, primarily
                for tests. When supplied, `session_store` is ignored
                (the override already owns its own persistence, if
                any).

            session_store:
                Optional explicit PostgreSQLSessionStore override. When
                omitted (and `session` is also omitted), a real
                PostgreSQL-backed store is constructed and initialized
                automatically, so the default CLI session is persisted.
        """

        self._runtime = runtime

        if session is not None:
            self._session = session
        else:
            store = session_store or _default_session_store(runtime)
            self._session = InterfaceSession(runtime, session_store=store)

        self._registry = registry or create_default_registry()

        self._color = color
        self._markdown_enabled = markdown
        self._stream_enabled = stream
        self._tool_footer_mode = tool_footer_mode

        event_bus = getattr(runtime, "event_bus", None)
        self._progress_renderer: ProgressRenderer | None = None

        if progress and event_bus is not None:
            if debug:
                self._progress_renderer = ConsoleProgressRenderer(
                    event_bus, color=color
                )
            else:
                self._progress_renderer = SpinnerProgressRenderer(
                    event_bus, color=color
                )

        self._setup_readline(history_file, history_size)

    # ------------------------------------------------------------------
    # REPL
    # ------------------------------------------------------------------

    def run(self) -> int:
        """
        Run the REPL until the user exits or input is closed.

        Returns:
            Process exit code.
        """

        self._print_banner()

        if self._progress_renderer is not None:
            self._progress_renderer.start()

        try:
            while True:
                try:
                    line = self._read_input()

                except EOFError:
                    self._print("")
                    self._print(_EXIT_MESSAGE)
                    break

                except KeyboardInterrupt:
                    self._print("")
                    continue

                if not line.strip():
                    continue

                # Minimal breathing room between the prompt line just
                # submitted and whatever this turn renders next -- the
                # status spinner, a command's own output, or the
                # answer -- so the two never visually touch. This is
                # the *only* gap before that output: the spinner's own
                # already-cleared line (or, if nothing was ever drawn
                # on it, that same still-empty line) doubles as the
                # single line the answer starts on, instead of opening
                # another blank line of its own -- see
                # `_handle_streamed_chat()`'s `ensure_answer_gap()`.
                self._print("")

                if self._registry.is_command(line):
                    if self._dispatch_command(line):
                        break

                    self._print_turn_separator()
                    continue

                try:
                    self._handle_chat(line)

                except KeyboardInterrupt:
                    # Requirement: Ctrl+C during execution stops the
                    # progress renderer immediately, leaves a clean
                    # prompt (no spinner residue, no half-rendered
                    # line), and never crashes the REPL. Restarting
                    # the renderer re-subscribes it for the next turn.
                    if self._progress_renderer is not None:
                        self._progress_renderer.stop()
                        self._progress_renderer.start()

                    self._print(_CANCELLED_MESSAGE)

                # Deliberately *two* blank lines after a turn's own
                # output (an answer, an error, or a command's result)
                # -- see `_print_turn_separator()` -- so every turn
                # reads as its own distinct conversational block when
                # scanning back through a long session, rather than
                # one unbroken wall of text.
                self._print_turn_separator()

        finally:
            if self._progress_renderer is not None:
                self._progress_renderer.stop()

            reset_terminal_title()

        return 0

    def _print_turn_separator(self) -> None:
        """
        Print the two blank lines that close out a turn -- twice the
        single, minimal gap printed just before a turn started (see
        the call site right after `_read_input()` in `run()`) -- so
        conversation turns visually group into distinct blocks instead
        of running together.
        """

        self._print("")
        self._print("")

    def _dispatch_command(self, line: str) -> bool:
        """
        Dispatch a slash command line.

        Returns:
            True if the REPL should stop after this command.
        """

        self._session.record(HistoryRole.COMMAND, line)

        try:
            result = self._registry.dispatch(line, self._session)

        except Exception as ex:  # noqa: BLE001 - surfaced to the user
            self._print(self._render_error(str(ex)))
            return False

        if result.new_session is not None:
            self._session = result.new_session

        if result.should_clear_screen:
            self._clear_screen()

        if result.text:
            self._print(result.text)

        return result.should_exit

    def _handle_chat(self, text: str) -> None:
        """
        Submit free text as a chat turn and display the result.
        """

        if self._stream_enabled:
            self._handle_streamed_chat(text)
            return

        # One timer for the entire request lifecycle: started the
        # moment the turn is handed to Brain, stopped only once the
        # answer/error below has completely finished printing --
        # never derived by summing any individual capability's own
        # `duration_seconds` (which `_print_tool_footer()` never even
        # sees), so it stays honest about orchestration overhead and
        # about turns that used no tool at all.
        started_at = time.monotonic()
        result = self._session.submit_text(text)

        # No gap printed here: by the time `submit_text()` returns,
        # the status spinner (if any was ever drawn) has already
        # cleared itself back to an empty line -- the same single
        # line opened just before this turn started (see `run()`) --
        # so the answer/error below starts there directly, instead of
        # opening a second blank line on top of the first.
        failed = self._print_error_if_failed(result)

        if not failed:
            if result.chat_response is None:
                return

            self._print(self._render(result.chat_response.message.content))

        # The footer is printed after an error too (see module
        # docstring/spec): a failed turn still reports what it tried
        # to use and how long the whole request took.
        self._print_tool_footer(
            result.chat_response.tool_invocations
            if result.chat_response is not None
            else (),
            succeeded=result.succeeded,
            elapsed_seconds=time.monotonic() - started_at,
        )

    def _handle_streamed_chat(self, text: str) -> None:
        """
        Submit free text as a chat turn, streaming the model's final
        answer token by token.
        """

        printer = StreamingPrinter(stream=sys.stdout)
        renderer = self._progress_renderer
        gap_printed = False

        def ensure_answer_gap() -> None:
            # Idempotent: the first thing that wants to render in the
            # "answer" slot -- the first streamed token, the
            # non-streaming fallback, or an error -- opens this gap
            # exactly once. Suspending the renderer here (rather than
            # only once streaming is confirmed to have happened) is
            # what lets streamed tokens safely share the terminal with
            # a still-in-flight spinner, present or future, without
            # either side needing to know about the other's timing.
            #
            # No newline is written here: suspending clears the
            # spinner's own line (if anything was ever drawn on it)
            # back to empty without moving off it, so the very first
            # token/error/fallback below starts on that same, single
            # line the turn already opened in `run()` -- not a second,
            # extra blank line stacked underneath it.
            nonlocal gap_printed

            if gap_printed:
                return

            if renderer is not None:
                renderer.suspend()

            gap_printed = True

        def on_token(fragment: str) -> None:
            ensure_answer_gap()
            printer(fragment)

        # Started before `submit_text()` -- the moment this turn is
        # handed to Brain -- exactly like the non-streaming path, so
        # the two report the total request time the same way.
        started_at = time.monotonic()

        try:
            result = self._session.submit_text(text, on_token=on_token)
        finally:
            if renderer is not None:
                renderer.resume()

        if printer.printed_any:
            sys.stdout.write("\n")
            sys.stdout.flush()

        # Whatever comes next -- an error, the non-streaming fallback,
        # or (with nothing streamed at all) directly the tool footer --
        # renders in the same "answer" slot, so it always opens this
        # gap first, exactly once.
        ensure_answer_gap()

        failed = self._print_error_if_failed(result)

        if not failed:
            if result.chat_response is None:
                return

            if not printer.printed_any:
                # The model answered without streaming any fragment
                # (e.g. a non-streaming-capable backend); fall back to
                # a single rendered print of the final answer.
                self._print(self._render(result.chat_response.message.content))

        # The footer is printed after an error too, and its timer
        # only stops here -- once the answer/error has completely
        # finished printing.
        self._print_tool_footer(
            result.chat_response.tool_invocations
            if result.chat_response is not None
            else (),
            succeeded=result.succeeded,
            elapsed_seconds=time.monotonic() - started_at,
        )

    def _print_error_if_failed(self, result: ChatTurnResult) -> bool:
        """
        Print the formatted error for an unsuccessful chat turn and
        return `True`, or do nothing and return `False` for a
        successful one.
        """

        if result.succeeded:
            return False

        self._print(
            self._render_error(result.error_message or "The request failed.")
        )
        return True

    def _print_tool_footer(
        self,
        invocations: Sequence[Any],
        *,
        succeeded: bool,
        elapsed_seconds: float,
    ) -> None:
        """
        Print the tool footer for one chat turn's `tool_invocations`,
        if `self._tool_footer_mode` calls for one -- see
        `tool_footer.render_tool_footer()`. `succeeded` and
        `elapsed_seconds` describe the whole request, not any one
        tool/capability within it.
        """

        footer = render_tool_footer(
            invocations,
            mode=self._tool_footer_mode,
            color=self._color,
            succeeded=succeeded,
            elapsed_seconds=elapsed_seconds,
        )

        if footer:
            self._print(footer)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def _read_input(self) -> str:
        """
        Read one logical line of input, supporting a trailing
        backslash (`\\`) as an explicit multiline continuation
        marker.
        """

        lines = [input(self._prompt())]

        while lines[-1].endswith(_LINE_CONTINUATION_SUFFIX):
            lines[-1] = lines[-1][: -len(_LINE_CONTINUATION_SUFFIX)]
            lines.append(input(_CONTINUATION_PROMPT))

        return "\n".join(lines)

    def _prompt(self) -> str:
        base = str(
            self._runtime.configuration.get("interfaces.cli.prompt", _DEFAULT_PROMPT)
        )
        return colorize(f"{base} ", Ansi.BOLD + Ansi.BLUE, enabled=self._color)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def _render(self, text: str) -> str:
        if self._markdown_enabled:
            return render_markdown(text, color=self._color)

        return text

    def _render_error(self, message: str) -> str:
        """
        Render an error for CLI display: a short `Error:` label on
        its own line, followed by the message itself on the next line
        (still passed through `_render()`, so Markdown in the message
        itself is unaffected), so an error always reads as its own
        distinct block instead of blending into the prompt or an
        ordinary answer. Purely a Console presentation choice; does
        not touch `interfaces.formatting.error_formatter`, which other,
        non-CLI, current or future Interfaces may still rely on for
        their own, differently-shaped error display.
        """

        label = colorize("Error:", Ansi.BOLD + Ansi.RED, enabled=self._color)
        return f"{label}\n{self._render(message)}"

    def _print(self, text: str) -> None:
        print(text)

    def _print_banner(self) -> None:
        banner = self._runtime.configuration.get(
            "interfaces.cli.banner", "PARIKA"
        )
        version = self._runtime.configuration.get(
            "application.version", "0.1.0"
        )

        self._print(
            colorize(f"{banner} v{version}", Ansi.BOLD, enabled=self._color)
        )
        self._print(colorize(_TAGLINE, Ansi.DIM, enabled=self._color))
        self._print(colorize(_READY_MESSAGE, Ansi.DIM, enabled=self._color))
        self._print("")

        reset_terminal_title()

    def _clear_screen(self) -> None:
        sys.stdout.write(_CLEAR_SCREEN_SEQUENCE)
        sys.stdout.flush()

    # ------------------------------------------------------------------
    # readline (history + arrow navigation)
    # ------------------------------------------------------------------

    def _setup_readline(
        self,
        history_file: Path | None,
        history_size: int,
    ) -> None:
        """
        Enable input history and arrow-key navigation via the
        standard library `readline` module, and persist history to
        `history_file` across runs when supplied.

        `readline` is not available on every platform (notably
        Windows without `pyreadline3`); when it cannot be imported,
        the CLI still runs, simply without persistent history or
        arrow-key recall beyond the current line.
        """

        try:
            import readline
        except ImportError:  # pragma: no cover - platform dependent
            return

        readline.set_history_length(history_size)

        if history_file is None:
            return

        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)

            if history_file.exists():
                readline.read_history_file(str(history_file))

        except OSError:  # pragma: no cover - best effort only
            return

        atexit.register(_write_history_file, history_file)


def _write_history_file(history_file: Path) -> None:
    """
    Persist `readline` history to `history_file`, best effort.
    """

    try:
        import readline
    except ImportError:  # pragma: no cover - platform dependent
        return

    try:
        readline.write_history_file(str(history_file))
    except OSError:  # pragma: no cover - best effort only
        pass


def main() -> int:
    """
    Entry point for the `parika` console script and `python -m parika`.
    """

    cli_args = parse_console_args()

    runtime = build_default_runtime(
        workspace_permission_prompt=CliWorkspacePermissionPrompt()
    )

    # Initialize Autonomous Runtime if enabled
    autonomous_runtime = None
    try:
        from parika.core.configuration.autonomous_config import load_autonomous_settings
        autonomous_settings = load_autonomous_settings(runtime.configuration)
        if autonomous_settings.enabled:
            from parika.core.autonomous.runtime import build_autonomous_runtime
            from parika.core.database.pool import PoolManager
            
            sync_pool = PoolManager.get_sync_pool()
            if sync_pool is not None:
                autonomous_runtime = build_autonomous_runtime(
                    sync_pool=sync_pool,
                    event_bus=runtime.event_bus,
                    logger=runtime.logger,
                    service_container=runtime.service_container,
                    capability_resolver=runtime.capability_resolver,
                    planner=runtime.planner,
                    capability_executor=runtime.capability_executor,
                    tool_manager=runtime.tool_manager,
                    provider_manager=runtime.provider_manager,
                    resource_manager=runtime.resource_manager,
                    policy_engine=runtime.policy_engine,
                    permission_manager=runtime.permission_manager,
                    workspace_permission_manager=runtime.workspace_permissions,
                    shared_implementation_registry=runtime.implementation_registry,
                    shared_skill_registry=runtime.skill_registry,
                )
                
                # Start the autonomous runtime (sync version for console)
                import asyncio
                asyncio.run(autonomous_runtime.start(auto_recover=True))
                
                # Set autonomous runtime on the runtime object
                runtime.autonomous_runtime = autonomous_runtime
    except Exception as e:
        runtime.logger.get_logger(__name__).error("Failed to initialize Autonomous Runtime: %s", e)

    history_file = runtime.configuration.get_project_root() / str(
        runtime.configuration.get(
            "interfaces.cli.history_file", "data/cli_history"
        )
    )

    is_tty = sys.stdout.isatty()

    debug = (
        cli_args.debug
        if cli_args.debug is not None
        else bool(runtime.configuration.get("interfaces.cli.debug", False))
    )

    app = CliApplication(
        runtime,
        color=bool(runtime.configuration.get("interfaces.cli.color", True))
        and is_tty,
        markdown=bool(
            runtime.configuration.get("interfaces.cli.markdown", True)
        ),
        stream=bool(runtime.configuration.get("interfaces.cli.stream", True)),
        progress=bool(
            runtime.configuration.get("interfaces.cli.progress", True)
        ),
        debug=debug,
        tool_footer_mode=ToolFooterMode.from_value(
            runtime.configuration.get(
                "interfaces.cli.tool_footer_mode", ToolFooterMode.SMART.value
            )
        ),
        history_file=history_file,
        history_size=int(
            runtime.configuration.get("interfaces.cli.history_size", 1000)
        ),
    )

    try:
        return app.run()

    finally:
        shutdown_runtime(runtime)


if __name__ == "__main__":
    raise SystemExit(main())
