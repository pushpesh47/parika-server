"""
Unit tests for GoogleCseSearchBackend.
"""

from __future__ import annotations

import json

import pytest

from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchNetworkError,
    WebSearchProviderUnavailableError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.search_backend_google_cse import (
    GoogleCseSearchBackend,
)
from parika.tools.web_search.transport import HttpResponse

SUCCESS_PAYLOAD = {
    "items": [
        {
            "title": "PARIKA - Wikipedia",
            "link": "https://en.wikipedia.org/wiki/PARIKA",
            "snippet": "PARIKA is an example intelligence kernel.",
        },
        {
            "title": "PARIKA Official Site",
            "link": "https://example.com/parika",
            "snippet": "Official homepage of PARIKA.",
        },
    ]
}


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


def _json_response(payload: object, *, status_code: int = 200) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        url="https://www.googleapis.com/customsearch/v1",
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


class TestSearch:
    def test_parses_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_json_response(SUCCESS_PAYLOAD))

        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="test-key",
            search_engine_id="test-cx",
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=5)

        assert len(results) == 2
        assert results[0].title == "PARIKA - Wikipedia"
        assert results[0].url == "https://en.wikipedia.org/wiki/PARIKA"
        assert results[0].snippet == (
            "PARIKA is an example intelligence kernel."
        )

        # Credentials are sent, never a hardcoded example value.
        assert "key=test-key" in transport.calls[0]
        assert "cx=test-cx" in transport.calls[0]

    def test_limits_to_max_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_json_response(SUCCESS_PAYLOAD))

        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="test-key",
            search_engine_id="test-cx",
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=1)

        assert len(results) == 1

    def test_returns_empty_tuple_when_no_items(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(_json_response({}))

        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="test-key",
            search_engine_id="test-cx",
        )

        assert backend.search("parika", max_results=5) == ()

    def test_rejects_empty_query(self) -> None:
        transport = _FakeTransport()
        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="test-key",
            search_engine_id="test-cx",
        )

        with pytest.raises(InvalidSearchQueryError):
            backend.search("", max_results=5)

    def test_missing_api_key_raises_provider_unavailable(self) -> None:
        transport = _FakeTransport()
        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="",
            search_engine_id="test-cx",
        )

        with pytest.raises(WebSearchProviderUnavailableError):
            backend.search("parika", max_results=5)

        # Never attempts a request that is guaranteed to fail.
        assert transport.calls == []

    def test_missing_search_engine_id_raises_provider_unavailable(
        self,
    ) -> None:
        transport = _FakeTransport()
        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="test-key",
            search_engine_id="",
        )

        with pytest.raises(WebSearchProviderUnavailableError):
            backend.search("parika", max_results=5)

        assert transport.calls == []

    def test_http_error_raises_network_error_with_message(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            _json_response(
                {"error": {"code": 403, "message": "API key invalid."}},
                status_code=403,
            )
        )

        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="bad-key",
            search_engine_id="test-cx",
        )

        with pytest.raises(WebSearchNetworkError) as excinfo:
            backend.search("parika", max_results=5)

        assert "API key invalid." in str(excinfo.value)

    def test_malformed_json_raises_network_error(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            HttpResponse(
                status_code=200,
                url="https://www.googleapis.com/customsearch/v1",
                headers={},
                body=b"not json",
            )
        )

        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="test-key",
            search_engine_id="test-cx",
        )

        with pytest.raises(WebSearchNetworkError):
            backend.search("parika", max_results=5)

    def test_retries_on_timeout_then_succeeds(self) -> None:
        transport = _FakeTransport()
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_response(_json_response(SUCCESS_PAYLOAD))

        backend = GoogleCseSearchBackend(
            transport,  # type: ignore[arg-type]
            api_key="test-key",
            search_engine_id="test-cx",
            max_attempts=2,
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=5)

        assert len(results) == 2
        assert len(transport.calls) == 2
