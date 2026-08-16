"""
Unit tests for `UrllibComfyUITransport`, mirroring
`tests/providers/ollama/test_ollama_transport.py`'s own shape.
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from parika.providers.comfyui.exceptions import (
    ComfyUIConnectionError,
    ComfyUIResponseError,
    ComfyUITimeoutError,
)
from parika.providers.comfyui.transport import UrllibComfyUITransport


class _FakeJsonResponse:
    def __init__(self, *, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeJsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class TestRequestJsonSuccess:
    def test_returns_parsed_object(self) -> None:
        transport = UrllibComfyUITransport()
        fake_response = _FakeJsonResponse(body=b'{"prompt_id": "abc"}')

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            return_value=fake_response,
        ):
            result = transport.request_json(
                "GET",
                "http://localhost:8188/history/abc",
                payload=None,
                timeout=5.0,
            )

        assert result == {"prompt_id": "abc"}

    def test_returns_parsed_list(self) -> None:
        transport = UrllibComfyUITransport()
        fake_response = _FakeJsonResponse(body=b'["a.safetensors", "b.safetensors"]')

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            return_value=fake_response,
        ):
            result = transport.request_json(
                "GET",
                "http://localhost:8188/models/diffusion_models",
                payload=None,
                timeout=5.0,
            )

        assert result == ["a.safetensors", "b.safetensors"]

    def test_empty_body_returns_empty_dict(self) -> None:
        transport = UrllibComfyUITransport()
        fake_response = _FakeJsonResponse(body=b"")

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            return_value=fake_response,
        ):
            result = transport.request_json(
                "GET", "http://localhost:8188/queue", payload=None, timeout=5.0
            )

        assert result == {}

    def test_sends_json_payload(self) -> None:
        transport = UrllibComfyUITransport()
        fake_response = _FakeJsonResponse(body=b"{}")
        captured: dict = {}

        def _capture(request, timeout):
            captured["data"] = request.data
            captured["headers"] = dict(request.header_items())
            return fake_response

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            side_effect=_capture,
        ):
            transport.request_json(
                "POST",
                "http://localhost:8188/prompt",
                payload={"prompt": {"1": {}}},
                timeout=5.0,
            )

        assert b'"prompt"' in captured["data"]
        assert captured["headers"]["Content-type"] == "application/json"


class TestRequestJsonErrors:
    def test_http_error_raises_response_error(self) -> None:
        transport = UrllibComfyUITransport()
        error = HTTPError(
            "http://localhost:8188/prompt", 400, "Bad Request", {}, None
        )

        with patch(
            "parika.providers.comfyui.transport.urlopen", side_effect=error
        ):
            with pytest.raises(ComfyUIResponseError):
                transport.request_json(
                    "POST", "http://localhost:8188/prompt", payload={}, timeout=5.0
                )

    def test_timeout_error_raises_timeout_error(self) -> None:
        transport = UrllibComfyUITransport()

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            side_effect=TimeoutError(),
        ):
            with pytest.raises(ComfyUITimeoutError):
                transport.request_json(
                    "GET", "http://localhost:8188/queue", payload=None, timeout=1.0
                )

    def test_connection_error_raises_connection_error(self) -> None:
        transport = UrllibComfyUITransport()

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            side_effect=URLError("refused"),
        ):
            with pytest.raises(ComfyUIConnectionError):
                transport.request_json(
                    "GET", "http://localhost:8188/queue", payload=None, timeout=1.0
                )

    def test_invalid_json_raises_response_error(self) -> None:
        transport = UrllibComfyUITransport()
        fake_response = _FakeJsonResponse(body=b"not json")

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            return_value=fake_response,
        ):
            with pytest.raises(ComfyUIResponseError):
                transport.request_json(
                    "GET", "http://localhost:8188/queue", payload=None, timeout=5.0
                )


class TestUploadMedia:
    def test_uploads_multipart_body_and_parses_response(self) -> None:
        transport = UrllibComfyUITransport()
        fake_response = _FakeJsonResponse(
            body=b'{"name": "foo.png", "subfolder": "", "type": "input"}'
        )
        captured: dict = {}

        def _capture(request, timeout):
            captured["data"] = request.data
            captured["content_type"] = request.get_header("Content-type")
            return fake_response

        with patch(
            "parika.providers.comfyui.transport.urlopen", side_effect=_capture
        ):
            result = transport.upload_media(
                "http://localhost:8188/upload/image",
                "foo.png",
                b"raw-bytes",
                timeout=5.0,
            )

        assert result == {"name": "foo.png", "subfolder": "", "type": "input"}
        assert b"raw-bytes" in captured["data"]
        assert captured["content_type"].startswith("multipart/form-data")

    def test_upload_error_raises_response_error(self) -> None:
        transport = UrllibComfyUITransport()
        error = HTTPError(
            "http://localhost:8188/upload/image", 500, "err", {}, None
        )

        with patch(
            "parika.providers.comfyui.transport.urlopen", side_effect=error
        ):
            with pytest.raises(ComfyUIResponseError):
                transport.upload_media(
                    "http://localhost:8188/upload/image",
                    "foo.png",
                    b"bytes",
                    timeout=5.0,
                )


class TestFetchBinary:
    def test_returns_raw_bytes(self) -> None:
        transport = UrllibComfyUITransport()
        fake_response = _FakeJsonResponse(body=b"\x89PNG-fake-bytes")

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            return_value=fake_response,
        ):
            result = transport.fetch_binary(
                "http://localhost:8188/view?filename=a.png", timeout=5.0
            )

        assert result == b"\x89PNG-fake-bytes"

    def test_connection_error_raises_connection_error(self) -> None:
        transport = UrllibComfyUITransport()

        with patch(
            "parika.providers.comfyui.transport.urlopen",
            side_effect=URLError("refused"),
        ):
            with pytest.raises(ComfyUIConnectionError):
                transport.fetch_binary(
                    "http://localhost:8188/view?filename=a.png", timeout=5.0
                )
