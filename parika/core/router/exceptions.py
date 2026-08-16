"""
PARIKA Router Exceptions

Defines the exception hierarchy used by Router.

All Router-specific exceptions derive from RouterError.
"""

from __future__ import annotations


class RouterError(Exception):
    """
    Base exception for all Router errors.
    """


class RouteAlreadyRegisteredError(RouterError):
    """
    Raised when attempting to register a route whose identifier is
    already registered.
    """


class RouteNotFoundError(RouterError):
    """
    Raised when a requested route is not registered.
    """


class NoMatchingRouteError(RouterError):
    """
    Raised when no registered route matches a request.
    """


class DispatchError(RouterError):
    """
    Raised when a selected route's handler raises an unhandled
    exception during dispatch.
    """
