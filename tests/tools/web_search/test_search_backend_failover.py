"""
Unit tests for `parika.tools.web_search.search_backend_failover`.

Provider *construction* (registry lookup, availability skipping,
single-vs-wrapped backend selection) is covered in
`test_provider_registry.py`; this file exercises `FailoverSearchBackend`
itself, in isolation, against scripted `SearchBackend` doubles.
"""

from __future__ import annotations

import pytest

from parika.core.logger.logger import Logger
from parika.core.configuration.configuration import Configuration
from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchAllProvidersFailedError,
    WebSearchNetworkError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.search_backend_failover import (
    FailoverSearchBackend,
)
from parika.tools.web_search.search_result import SearchResult


class _FakeBackend:
    """
    Scripted SearchBackend test double: either raises a scripted
    exception or returns a fixed result tuple.
    """

    def __init__(
        self,
        *,
        result: tuple[SearchResult, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(
        self, query: str, *, max_results: int
    ) -> tuple[SearchResult, ...]:
        self.calls.append((query, max_results))

        if self.error is not None:
            raise self.error

        assert self.result is not None
        return self.result


SUCCESS_RESULT = (SearchResult(title="PARIKA", url="https://example.com"),)


class TestFailoverSearchBackend:
    def test_returns_first_successful_provider_result(self) -> None:
        first = _FakeBackend(error=WebSearchTimeoutError("timed out"))
        second = _FakeBackend(result=SUCCESS_RESULT)

        backend = FailoverSearchBackend(
            [("google", first), ("duckduckgo", second)]
        )

        results = backend.search("parika", max_results=5)

        assert results == SUCCESS_RESULT
        assert first.calls == [("parika", 5)]
        assert second.calls == [("parika", 5)]

    def test_default_provider_is_tried_first(self) -> None:
        default = _FakeBackend(result=SUCCESS_RESULT)
        never_called = _FakeBackend(result=SUCCESS_RESULT)

        backend = FailoverSearchBackend(
            [("google", default), ("bing", never_called)]
        )

        backend.search("parika", max_results=5)

        assert default.calls == [("parika", 5)]
        assert never_called.calls == []

    def test_continues_past_multiple_failures(self) -> None:
        first = _FakeBackend(error=WebSearchTimeoutError("timed out"))
        second = _FakeBackend(error=WebSearchNetworkError("blocked"))
        third = _FakeBackend(result=SUCCESS_RESULT)

        backend = FailoverSearchBackend(
            [("google", first), ("bing", second), ("duckduckgo", third)]
        )

        results = backend.search("parika", max_results=5)

        assert results == SUCCESS_RESULT

    def test_raises_clean_failure_when_every_provider_fails(self) -> None:
        first = _FakeBackend(error=WebSearchTimeoutError("timed out"))
        second = _FakeBackend(error=WebSearchNetworkError("blocked"))

        backend = FailoverSearchBackend(
            [("google", first), ("bing", second)]
        )

        with pytest.raises(WebSearchAllProvidersFailedError) as excinfo:
            backend.search("parika", max_results=5)

        message = str(excinfo.value)
        assert "google" in message
        assert "bing" in message

    def test_invalid_query_propagates_immediately_without_failover(
        self,
    ) -> None:
        first = _FakeBackend(error=InvalidSearchQueryError("bad query"))
        second = _FakeBackend(result=SUCCESS_RESULT)

        backend = FailoverSearchBackend(
            [("google", first), ("duckduckgo", second)]
        )

        with pytest.raises(InvalidSearchQueryError):
            backend.search("", max_results=5)

        assert second.calls == []

    def test_requires_at_least_one_backend(self) -> None:
        with pytest.raises(ValueError):
            FailoverSearchBackend([])

    def test_logs_each_provider_failure(self) -> None:
        first = _FakeBackend(error=WebSearchTimeoutError("timed out"))
        second = _FakeBackend(result=SUCCESS_RESULT)

        backend = FailoverSearchBackend(
            [("google", first), ("duckduckgo", second)],
            logger=Logger(Configuration()),
        )

        # Must not raise even with a real Logger attached.
        backend.search("parika", max_results=5)
