"""
PARIKA Ollama Provider Exceptions

Defines the exception hierarchy used by the Ollama provider driver.

Every exception raised by this package derives from
`OllamaProviderError`. Where an equivalent, more general
`ProviderError` subtype already exists on `ProviderManager`'s public
exception vocabulary (see `parika.core.provider_manager.exceptions`),
the corresponding Ollama exception also derives from it so that
callers written against the generic Provider contract keep working
unmodified. `ProviderManager.execute()` does not wrap driver
exceptions (by design - see `PARIKA_Decision_Flow.md` section 8), so
these exceptions propagate to `CapabilityExecutor`, which wraps them
into `CapabilityExecutionError` regardless of their concrete type.
"""

from __future__ import annotations

from parika.core.provider_manager.exceptions import (
    ProviderCapabilityError,
    ProviderConnectionError,
    ProviderExecutionError,
    ProviderModelNotFoundError,
    ProviderTimeoutError,
)


class OllamaProviderError(Exception):
    """
    Base exception for all Ollama provider errors.
    """


class OllamaConnectionError(OllamaProviderError, ProviderConnectionError):
    """
    Raised when the Ollama server cannot be reached.

    This covers both "Ollama is not installed / not running" and
    "the configured `base_url` is unreachable".
    """


class OllamaTimeoutError(OllamaProviderError, ProviderTimeoutError):
    """
    Raised when a request to the Ollama server exceeds the configured
    timeout.
    """


class OllamaModelNotFoundError(OllamaProviderError, ProviderModelNotFoundError):
    """
    Raised when the requested model is not installed on the Ollama
    server.
    """


class OllamaResponseError(OllamaProviderError, ProviderExecutionError):
    """
    Raised when the Ollama server returns a malformed or unexpected
    response.
    """


class OllamaRequestError(OllamaProviderError, ProviderCapabilityError):
    """
    Raised when an unsupported or invalid request is supplied to the
    Ollama provider driver.
    """


class OllamaToolCallError(OllamaProviderError, ProviderExecutionError):
    """
    Raised when a tool call requested by an Ollama model cannot be
    resolved or fails while being executed through Brain.
    """
