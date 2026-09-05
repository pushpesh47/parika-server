"""
PARIKA Core - ProviderManager Component

Defines the exception hierarchy for the ProviderManager component.

All provider-related exceptions inherit from ProviderError.
The hierarchy provides normalized exceptions that are independent of
specific provider SDKs, allowing the rest of the PARIKA Core to handle
provider failures consistently.
"""

from __future__ import annotations


class ProviderError(Exception):
    """
    Base exception for all ProviderManager errors.
    """


class ProviderConfigurationError(ProviderError):
    """
    Raised when a provider is incorrectly configured.
    """


class ProviderRegistrationError(ProviderError):
    """
    Raised when provider registration or deregistration fails.
    """


class ProviderConnectionError(ProviderError):
    """
    Raised when a provider cannot be reached or a connection fails.
    """


class ProviderAuthenticationError(ProviderError):
    """
    Raised when authentication with a provider fails.
    """

class ProviderAuthorizationError(ProviderError):
    """Raised when a provider rejects an otherwise authenticated request."""

class ProviderRateLimitError(ProviderError):
    """Raised when a provider rate-limits a request."""

class ProviderResponseError(ProviderError):
    """Raised when a provider response is malformed or unusable."""

class ProviderServerError(ProviderError):
    """Raised for retryable provider-side server failures."""


class ProviderTimeoutError(ProviderError):
    """
    Raised when a provider operation exceeds the allowed timeout.
    """


class ProviderExecutionError(ProviderError):
    """
    Raised when a provider fails while executing a request.
    """


class ProviderModelNotFoundError(ProviderError):
    """
    Raised when the requested model is not available from a provider.
    """


class ProviderCapabilityError(ProviderError):
    """
    Raised when a requested operation requires capabilities or execution
    features that the selected model does not support.
    """
