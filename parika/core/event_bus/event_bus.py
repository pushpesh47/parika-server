"""
Event bus service for PARIKA.

This module provides a simple in-process publish/subscribe event bus.
Subscribers can register callable objects for named events and are
notified synchronously when those events are published.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from parika.core.logger.logger import Logger


class EventBus:
    """
    In-process publish/subscribe event bus.

    Events are identified by their string name. Subscribers are invoked
    synchronously in the order they were registered.
    """

    def __init__(self, logger: Logger) -> None:
        """
        Initialize the event bus.

        Args:
            logger:
                Application logger service.
        """

        self._logger = logger.get_logger(__name__)
        self._subscriptions: dict[str, list[Callable[[Any], None]]] = {}

    def subscribe(self, event_name: str, subscriber: Callable[[Any], None]) -> None:
        """
        Register a subscriber for an event.

        Duplicate registrations are ignored.

        Args:
            event_name:
                Name of the event.

            subscriber:
                Callable invoked when the event is published.
        """

        subscribers = self._subscriptions.setdefault(event_name, [])

        if subscriber not in subscribers:
            subscribers.append(subscriber)

    def unsubscribe(self, event_name: str, subscriber: Callable[[Any], None]) -> None:
        """
        Remove a subscriber from an event.

        If either the event or subscriber does not exist, this method
        silently returns.

        Args:
            event_name:
                Name of the event.

            subscriber:
                Subscriber to remove.
        """

        subscribers = self._subscriptions.get(event_name)

        if subscribers is None:
            return

        if subscriber not in subscribers:
            return

        subscribers.remove(subscriber)

        if not subscribers:
            del self._subscriptions[event_name]

    def publish(self, event_name: str, payload: Any = None) -> None:
        """
        Publish an event.

        Every registered subscriber is invoked synchronously in
        registration order. Exceptions raised by one subscriber are
        logged and do not prevent remaining subscribers from executing.

        Args:
            event_name:
                Name of the event.

            payload:
                Optional event payload.
        """

        subscribers = self._subscriptions.get(event_name)

        if not subscribers:
            return

        for subscriber in subscribers:
            try:
                subscriber(payload)

            except Exception:
                self._logger.exception(
                    "Unhandled exception while processing event '%s'.",
                    event_name,
                )