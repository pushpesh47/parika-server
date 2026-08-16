"""
PARIKA Web Search Tool - Search Provider Failover

Defines `FailoverSearchBackend`, a `SearchBackend` that tries an
ordered sequence of other `SearchBackend`s, falling over to the next
one whenever the current one errors, times out, or is otherwise
unavailable - continuing until one succeeds, or raising
`WebSearchAllProvidersFailedError` once every provider has failed.

This module is deliberately provider-agnostic: it has no knowledge of
DuckDuckGo, Google, Bing, Mojeek, Qwant, or Google Custom Search -
that knowledge belongs entirely to `provider_registry.py`, which is
also where every provider is actually instantiated (see its module
docstring for how to add a new one). Kept separate so the ordered-try
mechanism itself stays exactly as reusable and provider-agnostic as
`SearchBackend` itself.
"""

from __future__ import annotations

from collections.abc import Sequence

from parika.core.logger.logger import Logger

from .exceptions import InvalidSearchQueryError, WebSearchAllProvidersFailedError
from .protocol import SearchBackend
from .search_result import SearchResult


class FailoverSearchBackend:
    """
    A `SearchBackend` that tries an ordered sequence of other
    `SearchBackend`s, falling over to the next one whenever the
    current one raises.

    A search request's own validation errors
    (`InvalidSearchQueryError`) are never treated as a provider
    failure - every provider would reject the exact same invalid
    input identically, so failing over would only waste every
    provider's retry budget for no benefit - and propagate
    immediately instead.
    """

    def __init__(
        self,
        backends: Sequence[tuple[str, SearchBackend]],
        *,
        logger: Logger | None = None,
    ) -> None:
        """
        Initialize the failover backend.

        Args:
            backends:
                Every `(provider_name, backend)` pair to try, in the
                order they should be attempted. Must be non-empty.

            logger:
                Optional PARIKA Logger component used to report each
                provider failure at WARNING level before falling over
                to the next one.
        """

        if not backends:
            raise ValueError(
                "FailoverSearchBackend requires at least one backend."
            )

        self._backends = tuple(backends)
        self._logger = logger.get_logger(__name__) if logger else None

    def search(
        self,
        query: str,
        *,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        """
        Perform a web search, trying each configured provider in
        order until one succeeds.

        Raises:
            InvalidSearchQueryError:
                If `query` or `max_results` is invalid - raised
                immediately, without trying any provider, since every
                provider would reject it identically.

            WebSearchAllProvidersFailedError:
                If every configured provider failed, timed out, or
                was unavailable (including a timeout, network error,
                anti-bot/CAPTCHA challenge, HTTP error, or malformed
                response from any individual provider).
        """

        failures: list[tuple[str, Exception]] = []

        for name, backend in self._backends:
            try:
                return backend.search(query, max_results=max_results)

            except InvalidSearchQueryError:
                raise

            except Exception as ex:  # noqa: BLE001 - failover boundary
                failures.append((name, ex))

                if self._logger is not None:
                    self._logger.warning(
                        "Web search provider '%s' failed (%s); "
                        "trying the next configured provider.",
                        name,
                        ex,
                    )

        summary = "; ".join(
            f"{name}: {error}" for name, error in failures
        )

        raise WebSearchAllProvidersFailedError(
            f"Every configured web search provider failed: {summary}"
        )
