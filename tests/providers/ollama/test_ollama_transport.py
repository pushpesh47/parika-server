"""
Unit tests for UrllibOllamaTransport.

`urllib.request.urlopen` is patched so these tests never perform real
network I/O while still exercising the transport's real translation
logic for successes, HTTP errors, timeouts, other network failures,
and streamed NDJSON responses.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from parika.providers.ollama.exceptions import (
    OllamaConnectionError,
    OllamaResponseError,
    OllamaTimeoutError,
)
from parika.providers.ollama.transport import UrllibOllamaTransport


class _FakeJsonResponse:
    def __init__(self, *, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeJsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeStreamResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self) -> "_FakeStreamResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class TestRequestJsonSuccess:
    def test_returns_parsed_object(self) -> None:
        transport = UrllibOllamaTransport()

        fake_response = _FakeJsonResponse(body=b'{"version": "0.1.0"}')

        with patch(
            "parika.providers.ollama.transport.urlopen",
            return_value=fake_response,
        ):
            result = transport.request_json(
                "GET",
                "http://localhost:11434/api/version",
                payload=None,
                timeout=5.0,
            )

        assert result == {"version": "0.1.0"}

    def test_returns_empty_dict_for_empty_body(self) -> None:
        transport = UrllibOllamaTransport()

        with patch(
            "parika.providers.ollama.transport.urlopen",
            return_value=_FakeJsonResponse(body=b""),
        ):
            result = transport.request_json(
                "POST",
                "http://localhost:11434/api/show",
                payload={"model": "x"},
                timeout=5.0,
            )

        assert result == {}

    def test_sends_json_payload_with_content_type(self) -> None:
        transport = UrllibOllamaTransport()

        captured: dict[str, object] = {}

        def _fake_urlopen(request, timeout):  # noqa: ANN001
            captured["data"] = request.data
            captured["headers"] = dict(request.header_items())
            return _FakeJsonResponse(body=b"{}")

        with patch(
            "parika.providers.ollama.transport.urlopen",
            side_effect=_fake_urlopen,
        ):
            transport.request_json(
                "POST",
                "http://localhost:11434/api/show",
                payload={"model": "qwen3:8b"},
                timeout=5.0,
            )

        assert b"qwen3:8b" in captured["data"]  # type: ignore[operator]
        assert captured["headers"]["Content-type"] == "application/json"


class TestRequestJsonFailures:
    def test_translates_timeout_error(self) -> None:
        transport = UrllibOllamaTransport()

        with patch(
            "parika.providers.ollama.transport.urlopen",
            side_effect=TimeoutError(),
        ):
            with pytest.raises(OllamaTimeoutError):
                transport.request_json(
                    "GET", "http://localhost:11434/api/version",
                    payload=None, timeout=1.0,
                )

    def test_translates_url_error_wrapping_timeout(self) -> None:
        transport = UrllibOllamaTransport()

        with patch(
            "parika.providers.ollama.transport.urlopen",
            side_effect=URLError(TimeoutError()),
        ):
            with pytest.raises(OllamaTimeoutError):
                transport.request_json(
                    "GET", "http://localhost:11434/api/version",
                    payload=None, timeout=1.0,
                )

    def test_translates_other_url_error_to_connection_error(self) -> None:
        transport = UrllibOllamaTransport()

        with patch(
            "parika.providers.ollama.transport.urlopen",
            side_effect=URLError("connection refused"),
        ):
            with pytest.raises(OllamaConnectionError):
                transport.request_json(
                    "GET", "http://localhost:11434/api/version",
                    payload=None, timeout=1.0,
                )

    def test_http_error_is_translated_to_response_error(self) -> None:
        transport = UrllibOllamaTransport()

        http_error = HTTPError(
            "http://localhost:11434/api/show",
            404,
            "Not Found",
            {},
            BytesIO(b'{"error": "model \\"missing\\" not found"}'),
        )

        with patch(
            "parika.providers.ollama.transport.urlopen",
            side_effect=http_error,
        ):
            with pytest.raises(OllamaResponseError, match="not found"):
                transport.request_json(
                    "POST", "http://localhost:11434/api/show",
                    payload={"model": "missing"}, timeout=1.0,
                )

    def test_invalid_json_body_raises_response_error(self) -> None:
        transport = UrllibOllamaTransport()

        with patch(
            "parika.providers.ollama.transport.urlopen",
            return_value=_FakeJsonResponse(body=b"not json"),
        ):
            with pytest.raises(OllamaResponseError):
                transport.request_json(
                    "GET", "http://localhost:11434/api/version",
                    payload=None, timeout=1.0,
                )

    def test_non_object_json_body_raises_response_error(self) -> None:
        transport = UrllibOllamaTransport()

        with patch(
            "parika.providers.ollama.transport.urlopen",
            return_value=_FakeJsonResponse(body=b"[1, 2, 3]"),
        ):
            with pytest.raises(OllamaResponseError):
                transport.request_json(
                    "GET", "http://localhost:11434/api/version",
                    payload=None, timeout=1.0,
                )


class TestStreamLinesSuccess:
    def test_yields_one_object_per_line(self) -> None:
        transport = UrllibOllamaTransport()

        lines = [
            b'{"response": "Hel", "done": false}\n',
            b'{"response": "lo", "done": false}\n',
            b'{"response": "", "done": true}\n',
        ]

        with patch(
            "parika.providers.ollama.transport.urlopen",
            return_value=_FakeStreamResponse(lines),
        ):
            chunks = list(
                transport.stream_lines(
                    "POST",
                    "http://localhost:11434/api/generate",
                    payload={"model": "qwen3:8b", "prompt": "hi"},
                    timeout=5.0,
                )
            )

        assert [chunk["response"] for chunk in chunks] == ["Hel", "lo", ""]
        assert chunks[-1]["done"] is True

    def test_skips_blank_lines(self) -> None:
        transport = UrllibOllamaTransport()

        lines = [b"\n", b'{"done": true}\n']

        with patch(
            "parika.providers.ollama.transport.urlopen",
            return_value=_FakeStreamResponse(lines),
        ):
            chunks = list(
                transport.stream_lines(
                    "POST",
                    "http://localhost:11434/api/generate",
                    payload=None,
                    timeout=5.0,
                )
            )

        assert chunks == [{"done": True}]


class TestStreamLinesFailures:
    def test_http_error_before_streaming_raises_response_error(self) -> None:
        transport = UrllibOllamaTransport()

        http_error = HTTPError(
            "http://localhost:11434/api/chat",
            500,
            "Internal Server Error",
            {},
            BytesIO(b"boom"),
        )

        with patch(
            "parika.providers.ollama.transport.urlopen",
            side_effect=http_error,
        ):
            with pytest.raises(OllamaResponseError):
                list(
                    transport.stream_lines(
                        "POST", "http://localhost:11434/api/chat",
                        payload=None, timeout=1.0,
                    )
                )

    def test_connection_error_before_streaming_raises_connection_error(
        self,
    ) -> None:
        transport = UrllibOllamaTransport()

        with patch(
            "parika.providers.ollama.transport.urlopen",
            side_effect=URLError("unreachable"),
        ):
            with pytest.raises(OllamaConnectionError):
                list(
                    transport.stream_lines(
                        "POST", "http://localhost:11434/api/chat",
                        payload=None, timeout=1.0,
                    )
                )
