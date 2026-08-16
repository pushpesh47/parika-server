"""
PARIKA Ollama Provider - HTTP Transport

Defines the OllamaTransport contract used by the Ollama provider
driver to issue outbound HTTP requests against a local (or remote)
Ollama server, together with the default implementation built on the
Python standard library.

Isolating transport behind a small protocol allows the driver's
request-building and response-parsing logic to be exercised
deterministically in tests without depending on a running Ollama
server, while the default implementation remains a genuine, working
HTTP client for production use. This mirrors the pattern already
established by the Web Search Tool's `HttpTransport`
(`parika/tools/web_search/transport.py`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import logging
from .exceptions import (
    OllamaConnectionError,
    OllamaResponseError,
    OllamaTimeoutError,
)

DEFAULT_USER_AGENT = "PARIKA-OllamaProvider/1.0"
_logger = logging.getLogger(__name__)

@runtime_checkable
class OllamaTransport(Protocol):
    """
    Protocol implemented by every HTTP transport usable by the Ollama
    provider driver.
    """

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        """
        Perform a single, non-streaming JSON request.

        Args:
            method:
                HTTP method (e.g. "GET", "POST").

            url:
                Absolute URL to request.

            payload:
                Optional JSON request body.

            timeout:
                Maximum time, in seconds, to wait for the request to
                complete.

        Returns:
            The parsed JSON response body as a dict. An empty body
            is returned as an empty dict.

        Raises:
            OllamaConnectionError:
                If the server cannot be reached.

            OllamaTimeoutError:
                If the request exceeds `timeout`.

            OllamaResponseError:
                If the server returns a non-2xx status or a body that
                is not valid JSON.
        """
        ...

    def stream_lines(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> Iterator[dict[str, Any]]:
        """
        Perform a streaming request whose body is newline-delimited
        JSON (NDJSON), as produced by Ollama's `stream: true` APIs.

        Args:
            method:
                HTTP method (e.g. "POST").

            url:
                Absolute URL to request.

            payload:
                Optional JSON request body.

            timeout:
                Maximum time, in seconds, to wait for the connection
                and for each individual line to arrive.

        Yields:
            One parsed JSON object per non-empty line of the response
            body, in the order received.

        Raises:
            OllamaConnectionError:
                If the server cannot be reached.

            OllamaTimeoutError:
                If the request times out.

            OllamaResponseError:
                If the server returns a non-2xx status or a line that
                is not valid JSON.
        """
        ...


class UrllibOllamaTransport:
    """
    Default OllamaTransport implementation using the Python standard
    library's `urllib`.

    No third-party HTTP client dependency is introduced, in keeping
    with the project's standard-library-first preference.
    """

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT) -> None:
        """
        Initialize the transport.

        Args:
            user_agent:
                User-Agent header sent with every request.
        """

        self._user_agent = user_agent

    def request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        """
        Perform a single, non-streaming JSON request.
        """

        request = self._build_request(method, url, payload)
        # _logger.debug("Sending payload: method=%s url=%s payload=%s", method, url, payload)

        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = response.read()

        except HTTPError as ex:
            raise OllamaResponseError(
                self._describe_http_error(url, ex)
            ) from ex

        except TimeoutError as ex:
            raise OllamaTimeoutError(
                f"Request to '{url}' timed out after {timeout} seconds."
            ) from ex

        except URLError as ex:
            if isinstance(ex.reason, TimeoutError):
                raise OllamaTimeoutError(
                    f"Request to '{url}' timed out after "
                    f"{timeout} seconds."
                ) from ex

            raise OllamaConnectionError(
                f"Failed to reach the Ollama server at '{url}': "
                f"{ex.reason}"
            ) from ex

        return self._parse_json_body(url, body)

    def stream_lines(
        self,
        method: str,
        url: str,
        *,
        payload: Mapping[str, Any] | None = None,
        timeout: float,
    ) -> Iterator[dict[str, Any]]:
        """
        Perform a streaming NDJSON request.
        """

        request = self._build_request(method, url, payload)

        try:
            response = urlopen(request, timeout=timeout)  # noqa: S310

        except HTTPError as ex:
            raise OllamaResponseError(
                self._describe_http_error(url, ex)
            ) from ex

        except TimeoutError as ex:
            raise OllamaTimeoutError(
                f"Request to '{url}' timed out after {timeout} seconds."
            ) from ex

        except URLError as ex:
            if isinstance(ex.reason, TimeoutError):
                raise OllamaTimeoutError(
                    f"Request to '{url}' timed out after "
                    f"{timeout} seconds."
                ) from ex

            raise OllamaConnectionError(
                f"Failed to reach the Ollama server at '{url}': "
                f"{ex.reason}"
            ) from ex

        try:
            with response:
                for raw_line in response:
                    line = raw_line.strip()

                    if not line:
                        continue

                    yield self._parse_json_body(url, line)

        except TimeoutError as ex:
            raise OllamaTimeoutError(
                f"Streamed request to '{url}' timed out after "
                f"{timeout} seconds."
            ) from ex

        except URLError as ex:
            raise OllamaConnectionError(
                f"Connection to the Ollama server at '{url}' was "
                f"lost: {ex.reason}"
            ) from ex

    def _build_request(
        self,
        method: str,
        url: str,
        payload: Mapping[str, Any] | None,
    ) -> Request:
        """
        Build a `urllib.request.Request` for a JSON call.
        """

        headers = {"User-Agent": self._user_agent}
        data: bytes | None = None

        if payload is not None:
            data = json.dumps(dict(payload)).encode("utf-8")
            headers["Content-Type"] = "application/json"

        return Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )

    def _describe_http_error(self, url: str, ex: HTTPError) -> str:
        """
        Build a human-readable description of an HTTPError response.
        """

        body = ex.read() if ex.fp is not None else b""
        snippet = body.decode("utf-8", errors="replace")[:500]

        return (
            f"Ollama server at '{url}' returned HTTP {ex.code}: "
            f"{snippet}"
        )

    def _parse_json_body(self, url: str, body: bytes) -> dict[str, Any]:
        """
        Parse a JSON response body.

        Raises:
            OllamaResponseError:
                If `body` is not valid JSON.
        """

        if not body:
            return {}

        try:
            parsed = json.loads(body)

        except json.JSONDecodeError as ex:
            raise OllamaResponseError(
                f"Ollama server at '{url}' returned a response that "
                "is not valid JSON."
            ) from ex

        if not isinstance(parsed, dict):
            raise OllamaResponseError(
                f"Ollama server at '{url}' returned a JSON value that "
                "is not an object."
            )

        return parsed
