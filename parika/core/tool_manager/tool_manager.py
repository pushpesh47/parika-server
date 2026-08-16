"""
PARIKA Tool Manager

Provides the authoritative runtime registry for Tool objects.

The ToolManager is responsible for registering, storing, retrieving,
enumerating, and executing immutable Tool instances. It owns the runtime
tool registry and delegates execution to registered ToolDriver
implementations.

Responsibilities:
    - Register Tool objects.
    - Store immutable Tool instances.
    - Retrieve registered Tool objects.
    - Enumerate registered Tools.
    - Delegate execution to ToolDriver implementations.
    - Publish Tool lifecycle events.

Non-Responsibilities:
    - Tool creation.
    - Tool identifier generation.
    - Tool implementation logic.
    - Workflow execution.
    - Task execution.
    - Provider selection.
    - Retry logic.
    - Scheduling.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from threading import RLock
from uuid import uuid4

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.utilities.progress import ProgressEvent, ProgressReporter

from .driver import ToolDriver
from .events import (
    ToolExecuted,
    ToolExecutionFailed,
    ToolRegistered,
    ToolUnregistered,
)
from .exceptions import (
    InvalidToolError,
    ToolAlreadyRegisteredError,
    ToolExecutionError,
    ToolNotFoundError,
)
from .request import ToolRequest
from .response import ToolResponse
from .tool import Tool

_guard_execution_id: ContextVar[str | None] = ContextVar(
    "parika_tool_manager_guard_execution_id",
    default=None,
)
"""Identifies which `_execute_driver_with_progress_guard()` invocation
(if any) is currently "in control" of the calling execution context.

`EventBus` (`parika/core/event_bus/event_bus.py`) is a single, process-
wide, synchronous publish/subscribe hub: every subscriber currently
registered for a channel is invoked, regardless of which
`ToolManager.execute()` call happens to be publishing at that moment.
A guard that correlated events using only `progress_id`-independent
bookkeeping (i.e. "every `progress.*` event observed while I am
subscribed is mine") is therefore only correct under sequential/nested
execution, where exactly one guard's driver is ever actually running
at a time. It is unsound under genuine concurrency: two overlapping
`ToolManager.execute()` calls (different threads, same shared
`EventBus`) each install their own subscriber, so *both* guards observe
*both* executions' events, and one guard's failure-cleanup can
synthesize a terminal event for the other's still-running progress
node.

A `ContextVar` gives each guard invocation an execution-scoped identity
without touching `EventBus`, `ProgressEvent`, or `ProgressReporter`:

- Every OS thread starts with its own independent top-level
  `contextvars.Context`, so two concurrent threads calling
  `ToolManager.execute()` never observe each other's `ContextVar`
  value -- exactly the isolation genuine concurrency needs.
- A coroutine/Task started via `asyncio` inherits a *copy* of its
  creator's context, and mutations made inside one Task's copy never
  leak back into a sibling Task's copy -- the same isolation extends
  to future async/task-based concurrency without any redesign.
- Within one thread, setting this value for the duration of a guarded
  `driver.execute()` call and restoring the previous value in a
  `finally` block (see `_execute_driver_with_progress_guard()`) makes
  nesting "just work": an inner guard's own identity temporarily
  shadows its outer guard's identity for exactly the inner driver's
  call, so the outer guard's callbacks -- still subscribed the whole
  time -- see the inner execution's events but recognize (by comparing
  this value against their own captured identity) that those events do
  not belong to them, and vice versa.
"""


class ToolManager:
    """
    Thread-safe registry for immutable Tool objects.

    The ToolManager is the authoritative runtime registry for Tool
    instances. Each registered Tool has exactly one associated
    ToolDriver responsible for executing it.
    """

    def __init__(
        self,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the ToolManager.

        Args:
            event_bus:
                Event bus used to publish Tool lifecycle events.

            logger:
                Logger service used for diagnostic logging.
        """

        if type(event_bus) is not EventBus:
            raise TypeError(
                "event_bus must be an EventBus."
            )

        if type(logger) is not Logger:
            raise TypeError(
                "logger must be a Logger."
            )

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()

        self._tools: dict[str, Tool] = {}
        self._drivers: dict[str, ToolDriver] = {}

    def _validate_tool(
        self,
        tool: Tool,
    ) -> None:
        """
        Validate a Tool before performing registry operations.

        This method performs only manager-level validation.
        Intrinsic validation of Tool invariants is the responsibility
        of the Tool model itself.

        Args:
            tool:
                Tool instance to validate.

        Raises:
            InvalidToolError:
                If the supplied object is not a Tool instance.
        """

        if type(tool) is not Tool:
            raise InvalidToolError(
                "Expected a Tool instance."
            )

    def _require_tool(
        self,
        tool_id: str,
    ) -> Tool:
        """
        Retrieve a registered Tool.

        Args:
            tool_id:
                Identifier of the Tool.

        Returns:
            Registered immutable Tool.

        Raises:
            ToolNotFoundError:
                If the Tool is not registered.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._tools[tool_id]

        except KeyError as ex:
            raise ToolNotFoundError(
                f"Tool '{tool_id}' was not found."
            ) from ex

    def _validate_driver(
        self,
        driver: ToolDriver,
    ) -> None:
        """
        Validate a ToolDriver before performing registry operations.

        Args:
            driver:
                Driver instance to validate.

        Raises:
            InvalidToolError:
                If the supplied object does not implement ToolDriver.
        """

        if not isinstance(driver, ToolDriver):
            raise InvalidToolError(
                "Expected a ToolDriver instance."
            )

    def _require_driver(
        self,
        tool_id: str,
    ) -> ToolDriver:
        """
        Retrieve the ToolDriver associated with a Tool.

        Args:
            tool_id:
                Identifier of the Tool.

        Returns:
            Registered ToolDriver.

        Raises:
            ToolNotFoundError:
                If no ToolDriver is registered for the Tool.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._drivers[tool_id]

        except KeyError as ex:
            raise ToolNotFoundError(
                f"Driver for tool '{tool_id}' was not found."
            ) from ex

    def register(
        self,
        tool: Tool,
        driver: ToolDriver,
    ) -> None:
        """
        Register a Tool and its associated ToolDriver.

        Args:
            tool:
                Tool to register.

            driver:
                Driver responsible for executing the Tool.

        Raises:
            InvalidToolError:
                If the supplied object is not a Tool.

            ToolAlreadyRegisteredError:
                If a Tool with the same identifier is already registered.
        """

        self._validate_tool(tool)
        self._validate_driver(driver)

        with self._lock:
            if tool.id in self._tools:
                raise ToolAlreadyRegisteredError(
                    f"Tool '{tool.id}' is already registered."
                )

            self._tools[tool.id] = tool
            self._drivers[tool.id] = driver

            event = ToolRegistered(
                tool_id=tool.id,
            )

        self._event_bus.publish(
            "tool.registered",
            event,
        )

        self._logger.debug(
            "Registered tool '%s'.",
            tool.id,
        )

    def unregister(
        self,
        tool_id: str,
    ) -> None:
        """
        Remove a Tool and its associated ToolDriver.

        Args:
            tool_id:
                Identifier of the Tool to remove.

        Raises:
            ToolNotFoundError:
                If the Tool is not registered.
        """

        with self._lock:
            self._require_tool(tool_id)

            del self._tools[tool_id]
            del self._drivers[tool_id]

            event = ToolUnregistered(
                tool_id=tool_id,
            )

        self._event_bus.publish(
            "tool.unregistered",
            event,
        )

        self._logger.debug(
            "Unregistered tool '%s'.",
            tool_id,
        )

    def get(
        self,
        tool_id: str,
    ) -> Tool:
        """
        Retrieve a registered Tool.

        Args:
            tool_id:
                Identifier of the Tool.

        Returns:
            The registered immutable Tool.

        Raises:
            ToolNotFoundError:
                If the Tool is not registered.
        """

        with self._lock:
            return self._require_tool(tool_id)

    def contains(
        self,
        tool_id: str,
    ) -> bool:
        """
        Determine whether a Tool is registered.

        Args:
            tool_id:
                Identifier of the Tool.

        Returns:
            True if the Tool exists; otherwise False.
        """

        with self._lock:
            return tool_id in self._tools

    def get_all(self) -> tuple[Tool, ...]:
        """
        Retrieve all registered Tools.

        Returns:
            Tuple containing all registered immutable Tool objects.
        """

        with self._lock:
            return tuple(self._tools.values())

    def count(self) -> int:
        """
        Return the number of registered Tools.

        Returns:
            Number of registered Tools.
        """

        with self._lock:
            return len(self._tools)

    def _validate_request(
        self,
        request: ToolRequest,
    ) -> None:
        """
        Validate a ToolRequest before execution.

        Args:
            request:
                Request to validate.

        Raises:
            ToolExecutionError:
                If the supplied object is not a ToolRequest.
        """

        if type(request) is not ToolRequest:
            raise ToolExecutionError(
                "Expected a ToolRequest instance."
            )

    def _execute_driver_with_progress_guard(
        self,
        driver: ToolDriver,
        request: ToolRequest,
    ) -> ToolResponse:
        """
        Execute a ToolDriver while guaranteeing that every progress
        node the driver starts for itself receives exactly one
        terminal event.

        A ToolDriver commonly owns its own `ProgressReporter` (see
        `parika/core/utilities/progress.py`) and calls
        `self._progress.started()`/`.completed()`/`.failed()` around
        its own work. If `driver.execute()` raises before that
        driver's own `.completed()`/`.failed()` runs, the started
        node would otherwise stay open forever (the CLI spinner never
        returns to idle). This method closes that gap at the one
        shared boundary every ToolDriver already passes through,
        rather than requiring every driver author to remember a
        manual try/except -- see
        `docs/architecture/Core_Component_Responsibilities.md`'s
        Execution Progress addendum.

        It publishes a synthetic `failed()` event, reusing the exact
        identity (`source_id`, `progress_id`, `parent_progress_id`,
        `progress_path`, `task_id`) of any progress node observed
        going from `started` to unterminated during this call, only
        when `driver.execute()` raises. A driver that already
        reports its own `failed()` before its exception propagates
        (e.g. OCR, Document, Vision's detection drivers) is
        unaffected, since a node that already received a terminal
        event is never touched again.

        Execution ownership: this call establishes a fresh, unique
        identity in `_guard_execution_id` (a `ContextVar`) for exactly
        the duration of `driver.execute()`, and every `progress.*`
        event this guard observes is attributed to this call only when
        that `ContextVar` still holds this same identity at the moment
        the event is delivered. Because `EventBus` invokes subscribers
        synchronously, on the publisher's own thread/task, this is
        true precisely when the event was published by this call's own
        `driver.execute()` (directly, or by a nested guarded
        `ToolManager.execute()` call that has already restored this
        identity in its own `finally` block -- see the `_guard_
        execution_id` module docstring for why this isolates both
        concurrent executions on different threads/tasks and nested
        executions on the same thread). A concurrently running, *other*
        `ToolManager.execute()` call's events are therefore never
        recorded here, so this guard can never synthesize a terminal
        event for a progress node it does not itself own.

        Args:
            driver:
                ToolDriver to execute.

            request:
                Execution request.

        Returns:
            The driver's response, unchanged.

        Raises:
            Exception:
                Whatever `driver.execute()` itself raises, unchanged.
        """

        started_events: dict[str, ProgressEvent] = {}
        terminated_progress_ids: set[str] = set()

        execution_id = uuid4().hex

        def _owns_current_event() -> bool:
            return _guard_execution_id.get() == execution_id

        def _on_started(event: object) -> None:
            if isinstance(event, ProgressEvent) and _owns_current_event():
                started_events[event.progress_id] = event

        def _on_terminated(event: object) -> None:
            if isinstance(event, ProgressEvent) and _owns_current_event():
                terminated_progress_ids.add(event.progress_id)

        self._event_bus.subscribe("progress.started", _on_started)
        self._event_bus.subscribe("progress.completed", _on_terminated)
        self._event_bus.subscribe("progress.failed", _on_terminated)

        context_token: Token[str | None] = _guard_execution_id.set(
            execution_id
        )

        try:
            try:
                return driver.execute(request)

            except Exception as ex:
                try:
                    self._fail_unterminated_progress(
                        started_events,
                        terminated_progress_ids,
                        exception=ex,
                    )

                except Exception:
                    # The cleanup mechanism itself must never mask the
                    # original driver exception -- see this method's
                    # `Raises` contract and
                    # `CapabilityExecutor.execute()`'s matching
                    # "log and continue" pattern for a failed
                    # best-effort event publish
                    # (`parika/core/capability_executor/capability_executor.py`).
                    self._logger.exception(
                        "Failed to synthesize a terminal progress "
                        "event after a tool execution failure; the "
                        "original exception is preserved."
                    )

                raise

        finally:
            self._event_bus.unsubscribe("progress.started", _on_started)
            self._event_bus.unsubscribe("progress.completed", _on_terminated)
            self._event_bus.unsubscribe("progress.failed", _on_terminated)

            _guard_execution_id.reset(context_token)

    def _fail_unterminated_progress(
        self,
        started_events: dict[str, ProgressEvent],
        terminated_progress_ids: set[str],
        *,
        exception: Exception,
    ) -> None:
        """
        Publish a terminal `failed()` event for every progress node
        that started but never completed/failed during a guarded
        driver execution.

        Args:
            started_events:
                Every `progress.started` event observed during the
                guarded call, keyed by `progress_id`.

            terminated_progress_ids:
                Every `progress_id` that already received its own
                `completed()`/`failed()` event during the guarded
                call.

            exception:
                The exception that ended the guarded call, carried
                only into the synthetic event's `message`.
        """

        for progress_id, started_event in started_events.items():
            if progress_id in terminated_progress_ids:
                continue

            ProgressReporter(
                self._event_bus,
                started_event.source_id,
                task_id=started_event.task_id,
                progress_id=started_event.progress_id,
                parent_progress_id=started_event.parent_progress_id,
                progress_path=started_event.progress_path[:-1],
            ).failed(
                message=(
                    "Tool execution failed before reporting its own "
                    f"completion: {exception}"
                )
            )

    def execute(
        self,
        tool_id: str,
        request: ToolRequest,
    ) -> ToolResponse:
        """
        Execute a registered Tool.

        Execution is delegated to the Tool's registered ToolDriver.

        Every progress node the driver starts for itself is
        guaranteed to receive exactly one terminal event before this
        method returns or raises -- see
        `_execute_driver_with_progress_guard()`.

        Args:
            tool_id:
                Identifier of the Tool to execute.

            request:
                Execution request.

        Returns:
            Tool execution response.

        Raises:
            ToolNotFoundError:
                If the Tool is not registered.

            ToolExecutionError:
                If execution fails.
        """

        self._validate_request(request)

        with self._lock:
            tool = self._require_tool(tool_id)
            driver = self._require_driver(tool_id)

        try:
            response = self._execute_driver_with_progress_guard(
                driver, request
            )

            if type(response) is not ToolResponse:
                raise ToolExecutionError(
                    f"Tool '{tool_id}' returned an invalid response."
                )

        except Exception as ex:
            error = ToolExecutionError(
                f"Execution of tool '{tool_id}' failed: {ex}"
            )

            self._event_bus.publish(
                "tool.execution_failed",
                ToolExecutionFailed(
                    tool_id=tool.id,
                    request=request,
                    exception=error,
                ),
            )

            self._logger.exception(
                "Execution of tool '%s' failed.",
                tool.id,
            )

            raise error from ex

        self._event_bus.publish(
            "tool.executed",
            ToolExecuted(
                tool_id=tool.id,
                request=request,
                response=response,
            ),
        )

        self._logger.debug(
            "Executed tool '%s'.",
            tool.id,
        )

        return response