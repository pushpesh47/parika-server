"""
PARIKA News Tool Exceptions

Defines the exception hierarchy used by the News Tool.

All News Tool exceptions derive from `NewsToolError` so that
`ToolManager` can uniformly wrap them as `ToolExecutionError`, exactly
like every other Tool in PARIKA (see `runtime_info` and
`web_search`).
"""

from __future__ import annotations


class NewsToolError(Exception):
    """
    Base exception for all News Tool errors.
    """


class InvalidNewsArgumentError(NewsToolError):
    """
    Raised when a request is missing a required argument, or
    supplies an invalid one.
    """


class NewsTimeoutError(NewsToolError):
    """
    Raised when a feed fetch exceeds the configured timeout.
    """


class NewsNetworkError(NewsToolError):
    """
    Raised when a feed fetch fails for a reason other than a timeout.
    """


class NewsFeedError(NewsToolError):
    """
    Raised when every configured feed for a request failed to fetch
    or parse.
    """
