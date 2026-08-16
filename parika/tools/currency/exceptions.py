"""
PARIKA Currency Tool Exceptions

Defines the exception hierarchy used by the Currency Tool.

All Currency Tool exceptions derive from `CurrencyToolError` so that
`ToolManager` can uniformly wrap them as `ToolExecutionError`, exactly
like every other Tool in PARIKA (see `runtime_info` and
`web_search`).
"""

from __future__ import annotations


class CurrencyToolError(Exception):
    """
    Base exception for all Currency Tool errors.
    """


class InvalidCurrencyArgumentError(CurrencyToolError):
    """
    Raised when a request is missing a required argument, or supplies
    an invalid one (e.g. a currency code that is not a 3-letter
    ISO 4217-shaped string).
    """


class UnsupportedCurrencyPairError(CurrencyToolError):
    """
    Raised when a configured, reachable provider does not have a
    rate for the requested currency pair.
    """


class CurrencyTimeoutError(CurrencyToolError):
    """
    Raised when a network operation exceeds the configured timeout.
    """


class CurrencyNetworkError(CurrencyToolError):
    """
    Raised when a network operation fails for a reason other than a
    timeout, or a provider returns a malformed response.
    """


class CurrencyAllProvidersFailedError(CurrencyToolError):
    """
    Raised by `FailoverRateBackend` when every configured currency
    rate provider failed for a single request.
    """


class CurrencyProviderUnavailableError(CurrencyToolError):
    """
    Raised when a provider backend that requires configuration is
    invoked without it. Defensive safety net only - see
    `WebSearchProviderUnavailableError`'s identical rationale.
    """
