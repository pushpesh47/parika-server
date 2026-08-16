"""
Unit tests for UrllibHttpTransport.

`urllib.request.urlopen` is patched so these tests never perform real
network I/O while still exercising the transport's real translation
logic for successes, HTTP errors, timeouts, and other network
failures.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from parika.tools.web_search.exceptions import (
    WebSearchNetworkError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.transport import UrllibHttpTransport


class _FakeUrlopenResponse:
    def __init__(
        self,
        *,
        body: bytes,
        status: int,
        url: str,
        headers: dict[str, str],
    ) -> None:
        self._body = body
        self.status = status
        self.url = url
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class TestUrllibHttpTransportSuccess:
    def test_returns_normalized_response(self) -> None:
        transport = UrllibHttpTransport()

        fake_response = _FakeUrlopenResponse(
            body=b"<html>ok</html>",
            status=200,
            url="https://example.com/",
            headers={"Content-Type": "text/html"},
        )

        with patch(
            "parika.tools.web_search.transport.urlopen",
            return_value=fake_response,
        ):
            response = transport.get(
                "https://example.com/", timeout=5.0
            )

        assert response.status_code == 200
        assert response.url == "https://example.com/"
        assert response.body == b"<html>ok</html>"
        assert response.headers["Content-Type"] == "text/html"


class TestUrllibHttpTransportFailures:
    def test_translates_timeout_error(self) -> None:
        transport = UrllibHttpTransport()

        with patch(
            "parika.tools.web_search.transport.urlopen",
            side_effect=TimeoutError(),
        ):
            with pytest.raises(WebSearchTimeoutError):
                transport.get("https://example.com/", timeout=1.0)

    def test_translates_url_error_wrapping_timeout(self) -> None:
        transport = UrllibHttpTransport()

        with patch(
            "parika.tools.web_search.transport.urlopen",
            side_effect=URLError(TimeoutError()),
        ):
            with pytest.raises(WebSearchTimeoutError):
                transport.get("https://example.com/", timeout=1.0)

    def test_translates_other_url_error(self) -> None:
        transport = UrllibHttpTransport()

        with patch(
            "parika.tools.web_search.transport.urlopen",
            side_effect=URLError("name resolution failed"),
        ):
            with pytest.raises(WebSearchNetworkError):
                transport.get("https://example.com/", timeout=1.0)

    def test_returns_response_for_http_error(self) -> None:
        transport = UrllibHttpTransport()

        http_error = HTTPError(
            "https://example.com/missing",
            404,
            "Not Found",
            {"Content-Type": "text/html"},
            BytesIO(b"not found"),
        )

        with patch(
            "parika.tools.web_search.transport.urlopen",
            side_effect=http_error,
        ):
            response = transport.get(
                "https://example.com/missing", timeout=1.0
            )

        assert response.status_code == 404
        assert response.body == b"not found"
