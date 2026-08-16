"""
Unit tests for MojeekHtmlSearchBackend.
"""

from __future__ import annotations

import pytest

from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.search_backend_mojeek import (
    MojeekHtmlSearchBackend,
)
from parika.tools.web_search.transport import HttpResponse

SAMPLE_RESULTS_HTML = """
<ul id="results-standard">
  <li class="result">
    <a class="title" href="https://en.wikipedia.org/wiki/PARIKA">
      <h2>PARIKA - Wikipedia</h2>
    </a>
    <p class="s">PARIKA is an example intelligence kernel.</p>
  </li>
  <li class="result">
    <a class="title" href="https://example.com/parika">
      <h2>PARIKA Official Site</h2>
    </a>
    <p class="s">Official homepage of PARIKA.</p>
  </li>
</ul>
"""


class _FakeTransport:
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
        url="https://www.mojeek.com/search?q=parika",
        headers={"Content-Type": "text/html"},
        body=body.encode("utf-8"),
    )


class TestSearch:
    def test_parses_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = MojeekHtmlSearchBackend(
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
        assert results[1].snippet == "Official homepage of PARIKA."

    def test_limits_to_max_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = MojeekHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=1)

        assert len(results) == 1

    def test_returns_empty_tuple_when_no_results_found(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response("<html><body></body></html>"))

        backend = MojeekHtmlSearchBackend(transport)  # type: ignore[arg-type]

        assert backend.search("parika", max_results=5) == ()

    def test_rejects_empty_query(self) -> None:
        transport = _FakeTransport()
        backend = MojeekHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("", max_results=5)

    def test_rejects_non_positive_max_results(self) -> None:
        transport = _FakeTransport()
        backend = MojeekHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("parika", max_results=0)

    def test_retries_on_timeout_then_succeeds(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = MojeekHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            max_attempts=2,
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=5)

        assert len(results) == 2
        assert len(transport.calls) == 2

    def test_exhausts_retries_and_raises(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_error(WebSearchTimeoutError("timed out"))

        backend = MojeekHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            max_attempts=2,
            sleep=lambda seconds: None,
        )

        with pytest.raises(WebSearchTimeoutError):
            backend.search("parika", max_results=5)
