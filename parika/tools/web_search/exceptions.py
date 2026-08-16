"""
PARIKA Web Search Tool Exceptions

Defines the exception hierarchy used by the Web Search Tool.

All Web Search Tool exceptions derive from WebSearchToolError so that
ToolManager can uniformly wrap them as ToolExecutionError.
"""

from __future__ import annotations


class WebSearchToolError(Exception):
    """
    Base exception for all Web Search Tool errors.
    """


class InvalidSearchQueryError(WebSearchToolError):
    """
    Raised when a search request is missing a query or supplies an
    invalid one.
    """


class InvalidPageUrlError(WebSearchToolError):
    """
    Raised when a page fetch request supplies an invalid URL.
    """


class WebSearchTimeoutError(WebSearchToolError):
    """
    Raised when a network operation exceeds the configured timeout.
    """


class WebSearchNetworkError(WebSearchToolError):
    """
    Raised when a network operation fails for a reason other than a
    timeout.
    """


class WebSearchAllProvidersFailedError(WebSearchToolError):
    """
    Raised by `FailoverSearchBackend` when every configured search
    provider failed (or timed out, or was unavailable) for a single
    search request. Carries a summary of every provider's failure so
    the underlying cause of a total failure is never lost.
    """


class WebSearchProviderUnavailableError(WebSearchToolError):
    """
    Raised when a provider backend that requires configuration (e.g.
    `GoogleCseSearchBackend`) is invoked without it.

    Under normal operation this never happens: `provider_registry.py`
    proactively skips an unavailable provider before ever
    constructing its backend. This exists as a defensive safety net
    so such a backend never attempts a request that is guaranteed to
    fail even if it is somehow invoked directly, bypassing the
    registry (e.g. in a test).
    """
