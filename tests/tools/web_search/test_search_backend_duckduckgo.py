"""
Unit tests for DuckDuckGoHtmlSearchBackend.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchNetworkError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.search_backend_duckduckgo import (
    DuckDuckGoHtmlSearchBackend,
    _unwrap_ddg_redirect,
)
from parika.tools.web_search.transport import HttpResponse

SAMPLE_RESULTS_HTML = """
<div class="results">
  <div class="result">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FPARIKA&amp;rut=abc">
        PARIKA - Wikipedia
      </a>
    </h2>
    <a class="result__snippet">PARIKA is an example intelligence kernel.</a>
  </div>
  <div class="result">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="https://example.com/parika">
        PARIKA Official Site
      </a>
    </h2>
    <a class="result__snippet">Official homepage of PARIKA.</a>
  </div>
</div>
"""


class _FakeTransport:
    """Test double for HttpTransport with scriptable behavior."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._responses: list[HttpResponse | Exception] = []

    def queue_response(self, response: HttpResponse) -> None:
        self._responses.append(response)

    def queue_error(self, error: Exception) -> None:
        self._responses.append(error)

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)

        item = self._responses.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


def _html_response(body: str) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        url="https://html.duckduckgo.com/html/?q=parika",
        headers={"Content-Type": "text/html"},
        body=body.encode("utf-8"),
    )


class TestUnwrapDdgRedirect:
    def test_unwraps_redirect_url(self) -> None:
        href = (
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fx&rut=1"
        )

        assert _unwrap_ddg_redirect(href) == "https://example.com/x"

    def test_returns_direct_url_unchanged(self) -> None:
        assert (
            _unwrap_ddg_redirect("https://example.com/direct")
            == "https://example.com/direct"
        )

    def test_returns_empty_string_unchanged(self) -> None:
        assert _unwrap_ddg_redirect("") == ""


class TestSearch:
    def test_parses_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = DuckDuckGoHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=5)

        assert len(results) == 2
        assert results[0].title == "PARIKA - Wikipedia"
        assert results[0].url == "https://en.wikipedia.org/wiki/PARIKA"
        assert results[0].snippet == (
            "PARIKA is an example intelligence kernel."
        )
        assert results[1].url == "https://example.com/parika"

    def test_limits_to_max_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = DuckDuckGoHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=1)

        assert len(results) == 1

    def test_rejects_empty_query(self) -> None:
        transport = _FakeTransport()
        backend = DuckDuckGoHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("", max_results=5)

    def test_rejects_non_positive_max_results(self) -> None:
        transport = _FakeTransport()
        backend = DuckDuckGoHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("parika", max_results=0)

    def test_retries_on_timeout_then_succeeds(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        sleeps: list[float] = []

        backend = DuckDuckGoHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            max_attempts=3,
            backoff_seconds=0.1,
            sleep=sleeps.append,
        )

        results = backend.search("parika", max_results=5)

        assert len(results) == 2
        assert len(transport.calls) == 2
        assert sleeps == [0.1]

    def test_exhausts_retries_and_raises(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchNetworkError("boom"))
        transport.queue_error(WebSearchNetworkError("boom"))

        backend = DuckDuckGoHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            max_attempts=2,
            backoff_seconds=0.01,
            sleep=lambda seconds: None,
        )

        with pytest.raises(WebSearchNetworkError):
            backend.search("parika", max_results=5)

        assert len(transport.calls) == 2

    def test_raises_clear_error_on_anti_bot_challenge_page(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            _html_response(
                '<div class="anomaly-modal__mask">'
                "Unfortunately, bots use DuckDuckGo too."
                "</div>"
            )
        )

        backend = DuckDuckGoHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        with pytest.raises(WebSearchNetworkError, match="anti-bot"):
            backend.search("parika", max_results=5)
