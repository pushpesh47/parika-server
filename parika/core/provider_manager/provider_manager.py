"""
PARIKA Core - ProviderManager Component

Manages the registration, discovery, health, and execution of AI
providers.

ProviderManager is the central coordinator for the Provider subsystem.
It maintains the provider registry, manages provider drivers, delegates
provider-specific operations, and publishes provider lifecycle events.

ProviderManager does not implement provider-specific logic. All provider
communication is delegated to ProviderDriver implementations.
"""

from __future__ import annotations

from dataclasses import replace
from threading import RLock

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .driver import ProviderDriver
from .exceptions import (
    ProviderModelNotFoundError,
    ProviderRegistrationError,
)
from .provider import Provider
from .provider_model import ProviderModel
from .request import ProviderRequest
from .response import ProviderResponse


class ProviderManager:
    """
    Coordinates all registered AI providers.

    This class maintains the provider registry and delegates provider-
    specific operations to the associated ProviderDriver.
    """

    def __init__(
        self,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the ProviderManager.

        Args:
            event_bus:
                Event bus used to publish provider events.

            logger:
                Logger used for diagnostic logging.
        """
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._providers: dict[str, Provider] = {}
        self._drivers: dict[str, ProviderDriver] = {}

        self._lock = RLock()

    def register(
        self,
        provider: Provider,
        driver: ProviderDriver,
    ) -> None:
        """
        Register a provider and its associated driver.

        Args:
            provider:
                Provider to register.

            driver:
                Driver responsible for communicating with the provider.

        Raises:
            ProviderRegistrationError:
                If the provider is already registered.
        """
        with self._lock:
            if provider.id in self._providers:
                raise ProviderRegistrationError(
                    f"Provider '{provider.id}' is already registered."
                )

            self._providers[provider.id] = provider
            self._drivers[provider.id] = driver

        self._event_bus.publish(
            "provider.registered",
            {
                "provider_id": provider.id,
            },
        )

        self._logger.info(
            "Registered provider '%s'.",
            provider.id,
        )

    def unregister(
        self,
        provider_id: str,
    ) -> None:
        """
        Unregister a provider.

        Args:
            provider_id:
                Identifier of the provider.

        Raises:
            ProviderRegistrationError:
                If the provider is not registered.
        """
        with self._lock:
            if provider_id not in self._providers:
                raise ProviderRegistrationError(
                    f"Provider '{provider_id}' is not registered."
                )

            del self._providers[provider_id]
            del self._drivers[provider_id]

        self._event_bus.publish(
            "provider.unregistered",
            {
                "provider_id": provider_id,
            },
        )

        self._logger.info(
            "Unregistered provider '%s'.",
            provider_id,
        )


    def get(
        self,
        provider_id: str,
    ) -> Provider:
        """
        Return the registered provider.

        Args:
            provider_id:
                Identifier of the provider.

        Returns:
            The registered provider.

        Raises:
            ProviderRegistrationError:
                If the provider is not registered.
        """
        with self._lock:
            try:
                return self._providers[provider_id]
            except KeyError as exc:
                raise ProviderRegistrationError(
                    f"Provider '{provider_id}' is not registered."
                ) from exc


    def contains(
        self,
        provider_id: str,
    ) -> bool:
        """
        Determine whether a provider is registered.

        Args:
            provider_id:
                Identifier of the provider.

        Returns:
            True if the provider is registered; otherwise False.
        """
        with self._lock:
            return provider_id in self._providers


    def get_all(
        self,
    ) -> tuple[Provider, ...]:
        """
        Return all registered providers.

        Returns:
            A tuple containing all registered providers.
        """
        with self._lock:
            return tuple(self._providers.values())


    def count(
        self,
    ) -> int:
        """
        Return the number of registered providers.

        Returns:
            Number of registered providers.
        """
        with self._lock:
            return len(self._providers)

    def _get_provider_and_driver(
        self,
        provider_id: str,
    ) -> tuple[Provider, ProviderDriver]:
        """
        Return the registered provider and its associated driver.

        Args:
            provider_id:
                Identifier of the provider.

        Returns:
            A tuple containing the registered Provider and its
            associated ProviderDriver.

        Raises:
            ProviderRegistrationError:
                If the provider is not registered.
        """
        with self._lock:
            provider = self._providers.get(provider_id)
            driver = self._drivers.get(provider_id)

            if provider is None or driver is None:
                raise ProviderRegistrationError(
                    f"Provider '{provider_id}' is not registered."
                )

            return provider, driver

    def discover_models(
        self,
        provider_id: str,
    ) -> Provider:
        """
        Discover models for a registered provider.

        This method delegates model discovery to the associated
        ProviderDriver, updates the immutable Provider instance with the
        discovered models, and publishes a provider.models_discovered
        event.

        Args:
            provider_id:
                Identifier of the provider.

        Returns:
            The updated Provider instance.

        Raises:
            ProviderRegistrationError:
                If the provider is not registered.

            ProviderExecutionError:
                If model discovery fails.
        """
        provider, driver = self._get_provider_and_driver(provider_id)

        models = driver.discover_models()

        updated_provider = replace(
            provider,
            models=models,
        )

        with self._lock:
            self._providers[provider_id] = updated_provider

        self._event_bus.publish(
            "provider.models_discovered",
            {
                "provider_id": provider_id,
                "model_count": len(models),
            },
        )

        self._logger.info(
            "Discovered %d models for provider '%s'.",
            len(models),
            provider_id,
        )

        return updated_provider


    def refresh_health(
        self,
        provider_id: str,
    ) -> Provider:
        """
        Refresh the health information of a registered provider.

        This method delegates the health check to the associated
        ProviderDriver, updates the immutable Provider instance with the
        latest ProviderHealth, and publishes a
        provider.health_updated event.

        Args:
            provider_id:
                Identifier of the provider.

        Returns:
            The updated Provider instance.

        Raises:
            ProviderRegistrationError:
                If the provider is not registered.

            ProviderConnectionError:
                If the provider cannot be reached.

            ProviderTimeoutError:
                If the health check times out.
        """
        provider, driver = self._get_provider_and_driver(provider_id)

        health = driver.check_health()

        updated_provider = replace(
            provider,
            health=health,
        )

        with self._lock:
            self._providers[provider_id] = updated_provider

        self._event_bus.publish(
            "provider.health_updated",
            {
                "provider_id": provider_id,
                "available": health.available,
                "latency_ms": health.latency_ms,
            },
        )

        self._logger.info(
            "Updated health for provider '%s' (available=%s).",
            provider_id,
            health.available,
        )

        return updated_provider

    def execute(
        self,
        provider_id: str,
        model: ProviderModel,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """
        Execute a request using the specified provider model.

        This method delegates execution to the associated
        ProviderDriver.

        Args:
            provider_id:
                Identifier of the provider.

            model:
                Model selected for execution.

            request:
                Normalized provider request.

        Returns:
            A normalized provider response.

        Raises:
            ProviderRegistrationError:
                If the provider is not registered.

            ProviderModelNotFoundError:
                If the specified model does not belong to the provider.

            ProviderCapabilityError:
                If the selected model cannot satisfy the request.

            ProviderExecutionError:
                If execution fails.

            ProviderTimeoutError:
                If execution exceeds the allowed timeout.
        """
        provider, driver = self._get_provider_and_driver(provider_id)

        if model not in provider.models:
            raise ProviderModelNotFoundError(
                f"Model '{model.id}' is not registered for provider "
                f"'{provider_id}'."
            )

        response = driver.execute(
            model=model,
            request=request,
        )

        self._logger.info(
            "Executed request using provider '%s' and model '%s'.",
            provider_id,
            model.id,
        )

        return response