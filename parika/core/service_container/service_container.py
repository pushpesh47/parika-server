"""
PARIKA Service Container

Responsible for registering, storing, and providing
access to shared singleton services throughout PARIKA.

The ServiceContainer acts as the central registry for
application-wide services.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any


class ServiceContainer:
    """
    Central registry for shared services.

    Services are identified by their Python class and are
    stored as singleton instances.
    """

    def __init__(self) -> None:
        """Initialize the service container."""

        self._services: dict[type, Any] = {}

    def register(
        self,
        service_type: type,
        instance: Any,
    ) -> None:
        """
        Register a singleton service.

        Raises
        ------
        ValueError
            If the service is already registered.
        """

        if service_type in self._services:
            raise ValueError(
                f"Service '{service_type.__name__}' is already registered."
            )

        self._services[service_type] = instance

    def get(
        self,
        service_type: type,
    ) -> Any:
        """
        Retrieve a registered service.

        Raises
        ------
        LookupError
            If the service has not been registered.
        """

        if service_type not in self._services:
            raise LookupError(
                f"Service '{service_type.__name__}' is not registered."
            )

        return self._services[service_type]

    def has(
        self,
        service_type: type,
    ) -> bool:
        """
        Determine whether a service is registered.
        """

        return service_type in self._services

    def all(self):
        """
        Return a read-only view of all registered services.
        """

        return MappingProxyType(self._services)

    def clear(self) -> None:
        """
        Remove all registered services.

        This resets the container to its initial empty state,
        allowing it to be reused.
        """

        self._services.clear()