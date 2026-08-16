"""
PARIKA ComfyUI Provider - HTTP Transport

Defines the ComfyUITransport contract used by the ComfyUI provider
driver to issue outbound HTTP requests against a local (or remote)
ComfyUI server, together with the default implementation built on the
Python standard library.

Isolating transport behind a small protocol allows the driver's
workflow-construction and response-parsing logic to be exercised
deterministically in tests without depending on a running ComfyUI
server, while the default implementation remains a genuine, working
HTTP client for production use -- exactly the pattern already
established by `parika.providers.ollama.transport.OllamaTransport`.

Three operations are needed, corresponding to the three shapes of the
actual, installed ComfyUI HTTP API (confirmed against a live instance
during development; see the ComfyUI provider's own docstrings for
which concrete endpoints each is used for):

- `request_json()`: ordinary JSON request/response (`/prompt`,
  `/history/{id}`, `/models/{folder}`, `/system_stats`, `/queue`).
- `upload_media()`: multipart file upload (`/upload/image`, which
  ComfyUI also uses for video files -- there is no separate
  `/upload/video` endpoint).
- `fetch_binary()`: raw binary download (`/view`), used to retrieve a
  generated artifact's bytes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .exceptions import (
    ComfyUIConnectionError,
    ComfyUIResponseError,
    ComfyUITimeoutError,
)

DEFAULT_USER_AGENT = "PARIKA-ComfyUIProvider/1.0"


@runtime_checkable
class ComfyUITransport(Protocol):
    """
    Protocol implemented by every HTTP transport usable by the ComfyUI
    provider driver.
    """

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> Any:
        """
        Perform a single JSON request.

        Returns:
            The parsed JSON response body (a dict, or a list for
            endpoints such as `/models/{folder}` that return a bare
            JSON array). An empty body is returned as an empty dict.

        Raises:
            ComfyUIConnectionError:
                If the server cannot be reached.

            ComfyUITimeoutError:
                If the request exceeds `timeout`.

            ComfyUIResponseError:
                If the server returns a non-2xx status or a body that
                is not valid JSON.
        """
        ...

    def upload_media(
        self,
        url: str,
        filename: str,
        content: bytes,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        """
        Upload one media file (image or video) to ComfyUI's `input`
        store via `POST /upload/image` (ComfyUI's single upload
        endpoint for every media type a workflow's `LoadImage`/
        `LoadVideo` node can subsequently reference by name).

        Args:
            url:
                Absolute upload URL (`f"{base_url}/upload/image"`).

            filename:
                Filename to upload the content as.

            content:
                Raw file bytes.

        Returns:
            The parsed JSON response, e.g.
            `{"name": ..., "subfolder": ..., "type": "input"}`.
        """
        ...

    def fetch_binary(
        self,
        url: str,
        *,
        timeout: float,
    ) -> bytes:
        """
        Download raw bytes from a ComfyUI URL (`/view?filename=...`).
        """
        ...


class UrllibComfyUITransport:
    """
    Default ComfyUITransport implementation using the Python standard
    library's `urllib`.

    No third-party HTTP client dependency is introduced, in keeping
    with the project's standard-library-first preference (see
    `parika.providers.ollama.transport.UrllibOllamaTransport`).
    """

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._user_agent = user_agent

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout: float,
    ) -> Any:
        headers = {"User-Agent": self._user_agent}
        data: bytes | None = None

        if payload is not None:
            data = json.dumps(dict(payload)).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = response.read()

        except HTTPError as ex:
            raise ComfyUIResponseError(self._describe_http_error(url, ex)) from ex

        except TimeoutError as ex:
            raise ComfyUITimeoutError(
                f"Request to '{url}' timed out after {timeout} seconds."
            ) from ex

        except URLError as ex:
            if isinstance(ex.reason, TimeoutError):
                raise ComfyUITimeoutError(
                    f"Request to '{url}' timed out after {timeout} seconds."
                ) from ex

            raise ComfyUIConnectionError(
                f"Failed to reach the ComfyUI server at '{url}': {ex.reason}"
            ) from ex

        return self._parse_json_body(url, body)

    def upload_media(
        self,
        url: str,
        filename: str,
        content: bytes,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; '
            f'filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        body += content
        body += (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
            f"true\r\n--{boundary}--\r\n"
        ).encode("utf-8")

        request = Request(
            url,
            data=body,
            headers={
                "User-Agent": self._user_agent,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read()

        except HTTPError as ex:
            raise ComfyUIResponseError(self._describe_http_error(url, ex)) from ex

        except TimeoutError as ex:
            raise ComfyUITimeoutError(
                f"Upload to '{url}' timed out after {timeout} seconds."
            ) from ex

        except URLError as ex:
            if isinstance(ex.reason, TimeoutError):
                raise ComfyUITimeoutError(
                    f"Upload to '{url}' timed out after {timeout} seconds."
                ) from ex

            raise ComfyUIConnectionError(
                f"Failed to reach the ComfyUI server at '{url}': {ex.reason}"
            ) from ex

        parsed = self._parse_json_body(url, raw)

        if not isinstance(parsed, dict):
            raise ComfyUIResponseError(
                f"ComfyUI upload endpoint '{url}' returned a JSON value "
                "that is not an object."
            )

        return parsed

    def fetch_binary(self, url: str, *, timeout: float) -> bytes:
        request = Request(
            url, headers={"User-Agent": self._user_agent}, method="GET"
        )

        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.read()

        except HTTPError as ex:
            raise ComfyUIResponseError(self._describe_http_error(url, ex)) from ex

        except TimeoutError as ex:
            raise ComfyUITimeoutError(
                f"Request to '{url}' timed out after {timeout} seconds."
            ) from ex

        except URLError as ex:
            if isinstance(ex.reason, TimeoutError):
                raise ComfyUITimeoutError(
                    f"Request to '{url}' timed out after {timeout} seconds."
                ) from ex

            raise ComfyUIConnectionError(
                f"Failed to reach the ComfyUI server at '{url}': {ex.reason}"
            ) from ex

    def _describe_http_error(self, url: str, ex: HTTPError) -> str:
        body = ex.read() if ex.fp is not None else b""
        snippet = body.decode("utf-8", errors="replace")[:500]

        return f"ComfyUI server at '{url}' returned HTTP {ex.code}: {snippet}"

    def _parse_json_body(self, url: str, body: bytes) -> Any:
        if not body:
            return {}

        try:
            return json.loads(body)

        except json.JSONDecodeError as ex:
            raise ComfyUIResponseError(
                f"ComfyUI server at '{url}' returned a response that is "
                "not valid JSON."
            ) from ex
