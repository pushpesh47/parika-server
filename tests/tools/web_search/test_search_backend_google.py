"""
Unit tests for GoogleHtmlSearchBackend.
"""

from __future__ import annotations

import pytest

from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.search_backend_google import (
    GoogleHtmlSearchBackend,
    _unwrap_google_redirect,
)
from parika.tools.web_search.transport import HttpResponse

SAMPLE_RESULTS_HTML = """
<div id="search">
  <div class="g">
    <a href="https://en.wikipedia.org/wiki/PARIKA">
      <h3>PARIKA - Wikipedia</h3>
    </a>
    <div class="VwiC3b">PARIKA is an example intelligence kernel.</div>
  </div>
  <div class="g">
    <a href="/url?q=https://example.com/parika&amp;sa=U">
      <h3>PARIKA Official Site</h3>
    </a>
    <div class="VwiC3b">Official homepage of PARIKA.</div>
  </div>
</div>
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
        url="https://www.google.com/search?q=parika",
        headers={"Content-Type": "text/html"},
        body=body.encode("utf-8"),
    )


class TestUnwrapGoogleRedirect:
    def test_unwraps_redirect_url(self) -> None:
        href = "/url?q=https://example.com/x&sa=U"

        assert _unwrap_google_redirect(href) == "https://example.com/x"

    def test_returns_direct_url_unchanged(self) -> None:
        assert (
            _unwrap_google_redirect("https://example.com/direct")
            == "https://example.com/direct"
        )

    def test_returns_empty_string_unchanged(self) -> None:
        assert _unwrap_google_redirect("") == ""


MODERN_LAYOUT_HTML = """
<div id="rso">
  <div class="MjjYud">
    <div class="yuRUbf">
      <a jsname="UWckNb" href="https://en.wikipedia.org/wiki/PARIKA" data-jsarwt="1">
        <h3 class="LC20lb MBeuO DKV0Md">PARIKA - Wikipedia</h3>
      </a>
    </div>
    <div data-sncf="1" class="yXK7lf">
      PARIKA is an example intelligence kernel.
    </div>
  </div>
  <div class="MjjYud">
    <div class="ZReHs">
      <a jsname="UWckNb" href="/url?q=https://example.com/parika%3Fsource%3Dweb&amp;sa=U">
        <h3 class="LC20lb MBeuO DKV0Md">PARIKA Official Site</h3>
      </a>
    </div>
    <div data-sncf="1" class="yXK7lf">
      Official homepage of PARIKA.
    </div>
  </div>
</div>
"""
"""
A deliberately *different*-looking layout - new/renamed container and
title classes (`MjjYud`, `ZReHs` instead of `g`) - reproducing exactly
the kind of markup churn that made the parser previously report zero
results (Issue 3): only the structural `<a>`-before-`<h3>` shape is
preserved, none of the class names this parser used to depend on.
"""


class TestModernLayoutRobustness:
    """
    Regression coverage for Issue 3: the parser must keep working
    when Google renames every class it used to rely on, since it no
    longer depends on any specific class name for result detection.
    """

    def test_parses_results_from_renamed_classes(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response(MODERN_LAYOUT_HTML))

        backend = GoogleHtmlSearchBackend(
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
        assert results[1].title == "PARIKA Official Site"
        assert results[1].url == "https://example.com/parika?source=web"
        assert results[1].snippet == "Official homepage of PARIKA."

    def test_falls_back_to_generic_text_when_no_known_snippet_class(
        self,
    ) -> None:
        html = """
        <div class="completely-new-wrapper-name">
          <a href="https://example.com/parika">
            <h3>PARIKA Official Site</h3>
          </a>
          <span>Official homepage of PARIKA.</span>
        </div>
        """
        transport = _FakeTransport()
        transport.queue_response(_html_response(html))

        backend = GoogleHtmlSearchBackend(transport)  # type: ignore[arg-type]

        results = backend.search("parika", max_results=5)

        assert len(results) == 1
        assert results[0].title == "PARIKA Official Site"
        assert results[0].snippet == "Official homepage of PARIKA."

    def test_ignores_navigation_and_pagination_links(self) -> None:
        html = """
        <a href="/search?q=parika&start=10">Next</a>
        <a href="#">Search tools</a>
        <div class="g">
          <a href="https://example.com/parika"><h3>PARIKA</h3></a>
          <div class="VwiC3b">An intelligence kernel.</div>
        </div>
        """
        transport = _FakeTransport()
        transport.queue_response(_html_response(html))

        backend = GoogleHtmlSearchBackend(transport)  # type: ignore[arg-type]

        results = backend.search("parika", max_results=5)

        assert len(results) == 1
        assert results[0].url == "https://example.com/parika"


class TestSearch:
    def test_parses_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = GoogleHtmlSearchBackend(
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

        backend = GoogleHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=1)

        assert len(results) == 1

    def test_returns_empty_tuple_when_no_results_found(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_html_response("<html><body></body></html>"))

        backend = GoogleHtmlSearchBackend(transport)  # type: ignore[arg-type]

        assert backend.search("parika", max_results=5) == ()

    def test_rejects_empty_query(self) -> None:
        transport = _FakeTransport()
        backend = GoogleHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("", max_results=5)

    def test_rejects_non_positive_max_results(self) -> None:
        transport = _FakeTransport()
        backend = GoogleHtmlSearchBackend(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("parika", max_results=0)

    def test_retries_on_timeout_then_succeeds(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_response(_html_response(SAMPLE_RESULTS_HTML))

        backend = GoogleHtmlSearchBackend(
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

        backend = GoogleHtmlSearchBackend(
            transport,  # type: ignore[arg-type]
            max_attempts=2,
            sleep=lambda seconds: None,
        )

        with pytest.raises(WebSearchTimeoutError):
            backend.search("parika", max_results=5)
