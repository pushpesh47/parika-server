"""
PARIKA Context Manager

Provides the authoritative runtime registry for Context objects.

The ContextManager is responsible for registering, storing, retrieving,
updating, enumerating, and removing immutable Context instances. It owns
only transient runtime context storage and publishes lifecycle events
through the EventBus.

Responsibilities:
    - Register Context objects.
    - Store immutable Context instances.
    - Retrieve registered Context objects.
    - Replace existing Context objects.
    - Remove Context objects.
    - Enumerate registered Contexts.
    - Publish Context lifecycle events.

Non-Responsibilities:
    - Context creation.
    - Context identifier generation.
    - Workflow execution.
    - Task execution.
    - Lifecycle transition decisions.
    - Memory management.
    - Knowledge management.
    - Scheduling.
    - Provider selection.
    - Metadata interpretation.
"""

from __future__ import annotations

from threading import RLock

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .context import Context
from .events import (
    ContextRegistered,
    ContextRemoved,
    ContextUpdated,
)
from .exceptions import (
    ContextAlreadyExistsError,
    ContextNotFoundError,
    InvalidContextError,
)


class ContextManager:
    """
    Thread-safe registry for immutable Context objects.

    The ContextManager is the authoritative runtime registry for Context
    instances. All Context objects managed by this class are immutable.
    Updating a Context replaces the stored instance rather than modifying
    it in place.

    This component owns only transient runtime Context storage.
    """

    def __init__(self, event_bus: EventBus, logger: Logger) -> None:
        """
        Initialize the ContextManager.

        Args:
            event_bus:
                Event bus used to publish Context lifecycle events.

            logger:
                Logger instance used for diagnostic logging.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()

        self._contexts: dict[str, Context] = {}

    def _validate_context(
        self,
        context: Context,
    ) -> None:
        """
        Validate a Context object before performing a registry operation.

        This method performs only manager-level validation. Intrinsic
        validation of Context invariants is the responsibility of the
        Context model itself.

        Args:
            context:
                Context instance to validate.

        Raises:
            InvalidContextError:
                If the supplied object is not a Context instance.
        """

        if type(context) is not Context:
            raise InvalidContextError(
                "Expected a Context instance."
            )

    def _require_context(
        self,
        context_id: str,
    ) -> Context:
        """
        Retrieve a registered Context.

        Args:
            context_id:
                Identifier of the Context to retrieve.

        Returns:
            The registered immutable Context.

        Raises:
            ContextNotFoundError:
                If the Context is not registered.

        Notes:
            This helper assumes the caller already holds the registry lock.
        """

        try:
            return self._contexts[context_id]

        except KeyError as ex:
            raise ContextNotFoundError(
                f"Context '{context_id}' was not found."
            ) from ex

    def register(
        self,
        context: Context,
    ) -> None:
        """
        Register a new Context.

        The supplied Context must already be fully constructed and
        validated. The ContextManager stores the immutable instance
        without modification.

        Args:
            context:
                Context to register.

        Raises:
            InvalidContextError:
                If the supplied object is not a Context.

            ContextAlreadyExistsError:
                If a Context with the same identifier is already
                registered.
        """

        self._validate_context(context)

        with self._lock:
            if context.context_id in self._contexts:
                raise ContextAlreadyExistsError(
                    f"Context '{context.context_id}' is already registered."
                )

            self._contexts[context.context_id] = context

            event = ContextRegistered(
                context_id=context.context_id,
            )

        self._event_bus.publish(
            "context.registered",
            event,
        )

        self._logger.debug(
            "Registered context '%s'.",
            context.context_id,
        )

    def get(
        self,
        context_id: str,
    ) -> Context:
        """
        Retrieve a registered Context.

        Args:
            context_id:
                Identifier of the Context to retrieve.

        Returns:
            The registered immutable Context.

        Raises:
            ContextNotFoundError:
                If the requested Context is not registered.
        """

        with self._lock:
            return self._require_context(context_id)

    def contains(
        self,
        context_id: str,
    ) -> bool:
        """
        Determine whether a Context is registered.

        Args:
            context_id:
                Identifier of the Context to locate.

        Returns:
            True if the Context exists; otherwise False.
        """

        with self._lock:
            return context_id in self._contexts

    def update(
        self,
        context: Context,
    ) -> None:
        """
        Replace an existing Context.

        The supplied Context replaces the currently registered immutable
        Context having the same identifier.

        Args:
            context:
                Replacement Context.

        Raises:
            InvalidContextError:
                If the supplied object is not a Context.

            ContextNotFoundError:
                If the Context is not currently registered.
        """

        self._validate_context(context)

        with self._lock:
            self._require_context(context.context_id)

            self._contexts[context.context_id] = context

            event = ContextUpdated(
                context_id=context.context_id,
            )

        self._event_bus.publish(
            "context.updated",
            event,
        )

        self._logger.debug(
            "Updated context '%s'.",
            context.context_id,
        )

    def remove(
        self,
        context_id: str,
    ) -> None:
        """
        Remove a registered Context.

        Args:
            context_id:
                Identifier of the Context to remove.

        Raises:
            ContextNotFoundError:
                If the requested Context is not registered.
        """

        with self._lock:
            self._require_context(context_id)

            del self._contexts[context_id]

            event = ContextRemoved(
                context_id=context_id,
            )

        self._event_bus.publish(
            "context.removed",
            event,
        )

        self._logger.debug(
            "Removed context '%s'.",
            context_id,
        )

    def get_all(self) -> tuple[Context, ...]:
        """
        Retrieve all registered Context objects.

        Returns:
            An immutable snapshot containing every currently registered
            Context.

        Notes:
            The returned tuple represents a point-in-time snapshot of the
            registry. Subsequent modifications to the registry are not
            reflected in previously returned tuples.
        """

        with self._lock:
            return tuple(self._contexts.values())

    def count(self) -> int:
        """
        Return the number of registered Context objects.

        Returns:
            Total number of registered Context instances.
        """

        with self._lock:
            return len(self._contexts)