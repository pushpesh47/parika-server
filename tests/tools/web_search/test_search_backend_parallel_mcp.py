"""
Unit tests for Parallel MCP search backend.
"""

from __future__ import annotations

import json

import pytest

from parika.tools.web_search.config import WebSearchProviderConfig
from parika.tools.web_search.exceptions import (
    InvalidSearchQueryError,
    WebSearchNetworkError,
)
from parika.tools.web_search.provider_registry import (
    PROVIDER_REGISTRY,
    BackendTuning,
)
from parika.tools.web_search.search_backend_parallel_mcp import (
    ParallelMcpSearchBackend,
)
from parika.tools.web_search.transport import HttpResponse


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes | None, dict[str, str]]] = []
        self._responses: list[HttpResponse | Exception] = []

    def queue_response(self, response: HttpResponse) -> None:
        self._responses.append(response)

    def post(
        self,
        url: str,
        *,
        data: bytes | None,
        timeout: float,
        headers: dict[str, str],
    ) -> HttpResponse:
        self.calls.append((url, data, headers))

        item = self._responses.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


def _json_response(payload: dict[str, object]) -> HttpResponse:
    body = json.dumps(payload).encode("utf-8")
    return HttpResponse(
        status_code=200,
        url="https://search.parallel.ai/mcp",
        headers={"Content-Type": "application/json"},
        body=body,
    )


class TestSearch:
    def test_posts_json_rpc_and_parses_results(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "extract_id": "abc",
                                        "results": [
                                            {
                                                "url": "https://example.com",
                                                "title": "Example",
                                                "publish_date": None,
                                                "excerpts": [
                                                    "First excerpt"
                                                ],
                                                "full_content": None,
                                            }
                                        ],
                                        "usage": [],
                                        "session_id": "s1",
                                    }
                                ),
                            }
                        ]
                    },
                }
            )
        )

        backend = ParallelMcpSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        results = backend.search("parika", max_results=5)

        assert len(results) == 1
        assert results[0].title == "Example"
        assert results[0].url == "https://example.com"
        assert results[0].snippet == "First excerpt"
        assert results[0].display_url is None

    def test_rejects_empty_query(self) -> None:
        backend = ParallelMcpSearchBackend(object())  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("", max_results=5)

    def test_rejects_non_positive_max_results(self) -> None:
        backend = ParallelMcpSearchBackend(object())  # type: ignore[arg-type]

        with pytest.raises(InvalidSearchQueryError):
            backend.search("parika", max_results=0)

    def test_raises_on_malformed_payload(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(
            _json_response(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "content": [
                            {"type": "text", "text": "{not valid json}"},
                        ]
                    },
                }
            )
        )

        backend = ParallelMcpSearchBackend(
            transport,  # type: ignore[arg-type]
            sleep=lambda seconds: None,
        )

        with pytest.raises(WebSearchNetworkError):
            backend.search("parika", max_results=5)


class TestProviderRegistry:
    def test_parallel_mcp_is_registered(self) -> None:
        registration = PROVIDER_REGISTRY["parallel_mcp"]

        assert registration.is_available(WebSearchProviderConfig()) is True

        backend = registration.factory(
            object(),  # type: ignore[arg-type]
            WebSearchProviderConfig(),
            BackendTuning(),
        )

        assert isinstance(backend, ParallelMcpSearchBackend)
