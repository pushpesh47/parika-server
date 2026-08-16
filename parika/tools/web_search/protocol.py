"""
PARIKA Web Search Tool - Search Backend Protocol

Defines the `SearchBackend` contract every search provider
implementation (`search_backend_<provider>.py`) satisfies. Kept in its
own module, separate from any provider, so no provider's module is
ever the "home" of the shared contract every other provider - and
`FailoverSearchBackend`, `provider_registry.py`, and
`WebSearchToolDriver` - depend on.

Isolating the search backend behind a small protocol allows search
logic to be exercised deterministically in tests without depending on
a live search engine, while every concrete implementation remains a
genuine, working search client for production use.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .search_result import SearchResult


@runtime_checkable
class SearchBackend(Protocol):
    """
    Protocol implemented by every search backend usable by the Web
    Search Tool.
    """

    def search(
        self,
        query: str,
        *,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        """
        Perform a web search.

        Args:
            query:
                Search query text.

            max_results:
                Maximum number of results to return.

        Returns:
            Up to `max_results` SearchResult instances, in the order
            reported by the backend.
        """
        ...
