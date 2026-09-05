from __future__ import annotations
import json
from collections.abc import Iterator, Mapping
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

class OpenAICompatibleTransport(Protocol):
    def request_json(self, method: str, url: str, *, payload: Mapping[str, Any], headers: Mapping[str, str], timeout: float) -> dict[str, Any]: ...
    def stream_lines(self, method: str, url: str, *, payload: Mapping[str, Any], headers: Mapping[str, str], timeout: float) -> Iterator[dict[str, Any]]: ...

class UrllibOpenAICompatibleTransport:
    def request_json(self, method, url, *, payload, headers, timeout):
        req = Request(url, data=json.dumps(dict(payload)).encode(), headers=dict(headers), method=method)
        try:
            with urlopen(req, timeout=timeout) as response:  # noqa: S310
                raw = response.read()
        except HTTPError:
            raise
        except TimeoutError as ex:
            raise TimeoutError from ex
        except URLError as ex:
            raise ConnectionError from ex
        return self._decode(raw)

    def stream_lines(self, method, url, *, payload, headers, timeout):
        req = Request(url, data=json.dumps(dict(payload)).encode(), headers=dict(headers), method=method)
        try:
            response = urlopen(req, timeout=timeout)  # noqa: S310
        except TimeoutError as ex:
            raise TimeoutError from ex
        except URLError as ex:
            raise ConnectionError from ex
        with response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    return
                yield self._decode(line.encode())

    @staticmethod
    def _decode(raw: bytes) -> dict[str, Any]:
        value = json.loads(raw) if raw else {}
        if not isinstance(value, dict):
            raise ValueError("provider response is not an object")
        return value
