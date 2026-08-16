"""
PARIKA Core - ProviderManager Component

Defines the abstract ProviderDriver interface.

ProviderDriver is the bridge between the normalized PARIKA Core and
provider-specific implementations. Concrete drivers translate between
PARIKA domain objects and native provider SDKs or APIs.

ProviderDriver implementations are responsible only for provider
communication. Routing, lifecycle management, retries, logging,
registration, and policy enforcement are handled elsewhere in the
PARIKA Core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .provider_health import ProviderHealth
from .provider_model import ProviderModel
from .request import ProviderRequest
from .response import ProviderResponse


class ProviderDriver(ABC):
    """
    Abstract interface implemented by all provider drivers.

    A ProviderDriver encapsulates all provider-specific communication
    required to discover models, check provider health, and execute
    requests against a selected model.
    """

    @abstractmethod
    def discover_models(self) -> frozenset[ProviderModel]:
        """
        Discover models supported by the provider.

        Returns:
            A normalized collection of discovered provider models.

        Raises:
            ProviderConnectionError:
                If the provider cannot be reached.

            ProviderAuthenticationError:
                If authentication fails.

            ProviderExecutionError:
                If model discovery fails.
        """
        raise NotImplementedError

    @abstractmethod
    def check_health(self) -> ProviderHealth:
        """
        Check the operational health of the provider.

        Returns:
            The normalized provider health information.

        Raises:
            ProviderConnectionError:
                If the provider cannot be reached.

            ProviderTimeoutError:
                If the health check times out.
        """
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        model: ProviderModel,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """
        Execute a request using the specified model.

        Args:
            model:
                The model selected by ProviderManager.

            request:
                The normalized request to execute.

        Returns:
            A normalized provider response.

        Raises:
            ProviderModelNotFoundError:
                If the requested model is unavailable.

            ProviderCapabilityError:
                If the model cannot satisfy the request.

            ProviderExecutionError:
                If execution fails.

            ProviderTimeoutError:
                If execution exceeds the allowed timeout.
        """
        raise NotImplementedError