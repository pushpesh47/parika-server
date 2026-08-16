"""
Unit tests for PageFetcher.
"""

from __future__ import annotations

import pytest

from parika.tools.web_search.exceptions import (
    InvalidPageUrlError,
    WebSearchNetworkError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.page_fetcher import PageFetcher
from parika.tools.web_search.transport import HttpResponse

SAMPLE_PAGE_HTML = """
<html>
<head>
<title>PARIKA</title>
<meta name="description" content="Personal intelligence kernel.">
</head>
<body>
<p>PARIKA coordinates AI, tools, and memory.</p>
</body>
</html>
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


def _page_response(
    body: str,
    *,
    url: str = "https://example.com/parika",
    status_code: int = 200,
) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        url=url,
        headers={"Content-Type": "text/html; charset=utf-8"},
        body=body.encode("utf-8"),
    )


class TestFetch:
    def test_extracts_page_content(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_page_response(SAMPLE_PAGE_HTML))

        fetcher = PageFetcher(transport)  # type: ignore[arg-type]

        page = fetcher.fetch("https://example.com/parika")

        assert page.title == "PARIKA"
        assert page.description == "Personal intelligence kernel."
        assert "coordinates AI" in page.text
        assert page.status_code == 200
        assert page.content_type == "text/html; charset=utf-8"
        assert page.content_length == len(
            SAMPLE_PAGE_HTML.encode("utf-8")
        )
        assert page.final_url == "https://example.com/parika"

    def test_reports_final_url_after_redirect(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            _page_response(
                SAMPLE_PAGE_HTML,
                url="https://example.com/final",
            )
        )

        fetcher = PageFetcher(transport)  # type: ignore[arg-type]

        page = fetcher.fetch("https://example.com/parika")

        assert page.url == "https://example.com/parika"
        assert page.final_url == "https://example.com/final"

    def test_rejects_empty_url(self) -> None:
        transport = _FakeTransport()
        fetcher = PageFetcher(transport)  # type: ignore[arg-type]

        with pytest.raises(InvalidPageUrlError):
            fetcher.fetch("")

    def test_retries_on_network_error_then_succeeds(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchNetworkError("boom"))
        transport.queue_response(_page_response(SAMPLE_PAGE_HTML))

        sleeps: list[float] = []

        fetcher = PageFetcher(
            transport,  # type: ignore[arg-type]
            max_attempts=3,
            backoff_seconds=0.2,
            sleep=sleeps.append,
        )

        page = fetcher.fetch("https://example.com/parika")

        assert page.title == "PARIKA"
        assert sleeps == [0.2]

    def test_exhausts_retries_and_raises_timeout(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchTimeoutError("timeout"))
        transport.queue_error(WebSearchTimeoutError("timeout"))

        fetcher = PageFetcher(
            transport,  # type: ignore[arg-type]
            max_attempts=2,
            backoff_seconds=0.01,
            sleep=lambda seconds: None,
        )

        with pytest.raises(WebSearchTimeoutError):
            fetcher.fetch("https://example.com/parika")
