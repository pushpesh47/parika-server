"""
Unit tests for BingHtmlSearchBackend.
"""

from __future__ import annotations

import pytest

from parika.tools.web_search.search_backend_bing import (
    BingHtmlSearchBackend,
    _decode_bing_redirect,
)
from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.transport import HttpResponse

SAMPLE_RESULTS_HTML = """
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://en.wikipedia.org/wiki/PARIKA">PARIKA - Wikipedia</a></h2>
    <div class="b_caption">
      <p>PARIKA is an example intelligence kernel.</p>
    </div>
  </li>
  <li class="b_algo">
    <h2><a href="https://example.com/parika">PARIKA Official Site</a></h2>
    <div class="b_caption">
      <p>Official homepage of PARIKA.</p>
    </div>
  </li>
</ol>
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
        url="https://www.bing.com/search?q=parika",
        headers={"Content-Type": "text/html"},
        body=body.encode("utf-8"),
    )


class TestDecodeBingRedirect:
    def test_decodes_ck_a_redirect(self) -> None:
        href = (
            "https://www.bing.com/ck/a?!&&p=254be3c5&"
            "u=a1aHR0cHM6Ly93d3cubmR0di5jb20vbGF0ZXN0&ntb=1"
        )

        assert _decode_bing_redirect(href) == "https://www.ndtv.com/latest"

    def test_decodes_relative_ck_a_redirect(self) -> None:
        href = "/ck/a?!&&p=abc&u=a1aHR0cHM6Ly93d3cubmR0di5jb20vbGF0ZXN0"

        assert _decode_bing_redirect(href) == "https://www.ndtv.com/latest"

    def test_returns_direct_url_unchanged(self) -> None:
        assert (
            _decode_bing_redirect("https://example.com/direct")
            == "https://example.com/direct"
        )

    def test_returns_empty_string_unchanged(self) -> None:
        assert _decode_bing_redirect("") == ""

    def test_returns_unrecognized_redirect_shape_unchanged(self) -> None:
        href = "https://www.bing.com/ck/a?u=not-valid-base64!!!"

        assert _decode_bing_redirect(href) == href

    def test_ignores_non_bing_ck_a_lookalike(self) -> None:
        href = "https://example.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbQ=="

        assert _decode_bing_redirect(href) == href


class TestRealWorldMarkupRobustness:
    """
    Regression coverage for Issues 4, 5, and 8: a breadcrumb/citation
    row rendered *before* the `<h2>` title (the layout that produced
    garbled titles like "ndtv.comhttps://www.ndtv.com \u203a latest"),
    a `bing.com/ck/a` click-tracking redirect instead of a direct URL,
    and a separately exposed `display_url`.
    """

    def test_title_excludes_leading_breadcrumb_row(self) -> None:
        html = """
        <li class="b_algo">
          <div class="tptt">
            <a href="https://www.ndtv.com/latest">
              <cite>https://www.ndtv.com &rsaquo; latest</cite>
            </a>
          </div>
          <h2>
            <a href="https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1aHR0cHM6Ly93d3cubmR0di5jb20vbGF0ZXN0&amp;ntb=1">
              Latest News - NDTV
            </a>
          </h2>
          <div class="b_caption">
            <p>Get the latest news updates from NDTV.</p>
          </div>
        </li>
        """
        transport = _FakeTransport()
        transport.queue_response(_html_response(html))

        backend = BingHtmlSearchBackend(transport)  # type: ignore[arg-type]

        results = backend.search("ndtv", max_results=5)

        assert len(results) == 1
        assert results[0].title == "Latest News - NDTV"
        assert results[0].url == "https://www.ndtv.com/latest"
        assert results[0].display_url == (
            "https://www.ndtv.com \u203a latest"
        )
        assert results[0].snippet == "Get the latest news updates from NDTV."


class TestSearch:
    def test_parses_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = BingHtmlSearchBackend(
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

        backend = BingHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=1)

        assert len(results) == 1

    def test_returns_empty_tuple_when_no_results_found(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response("<html><body></body></html>"))

        backend = BingHtmlSearchBackend(transport)  # type: ignore[arg-type]

        assert backend.search("parika", max_results=5) == ()

    def test_rejects_empty_query(self) -> None:
        transport = _FakeTransport()
        backend = BingHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("", max_results=5)

    def test_rejects_non_positive_max_results(self) -> None:
        transport = _FakeTransport()
        backend = BingHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("parika", max_results=0)

    def test_retries_on_timeout_then_succeeds(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = BingHtmlSearchBackend(
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

        backend = BingHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            max_attempts=2,
            sleep=lambda seconds: None,
        )

        with pytest.raises(WebSearchTimeoutError):
            backend.search("parika", max_results=5)
