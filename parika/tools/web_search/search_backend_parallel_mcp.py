"""
PARIKA Web Search Tool - Parallel MCP Search Backend

A `SearchBackend` implementation backed by Parallel's hosted MCP
endpoint. Instead of scraping HTML search results, this backend sends
JSON-RPC requests to Parallel's `web_fetch` tool and converts the
returned structured results into `SearchResult` objects.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from time import sleep as time_sleep
from uuid import uuid4

from .backend_support import (
    decode_body,
    fetch_with_retry,
    raise_if_http_error,
    validate_search_arguments,
)
from .exceptions import WebSearchNetworkError
from .search_result import SearchResult
from .transport import HttpTransport

logger = logging.getLogger(__name__)

DEFAULT_PARALLEL_MCP_ENDPOINT = "https://search.parallel.ai/mcp"
DEFAULT_PARALLEL_MCP_MODEL_NAME = "gpt-5.5"


class ParallelMcpSearchBackend:
    """
    SearchBackend implementation using Parallel's hosted MCP endpoint.
    """

    def __init__(
        self,
        transport: HttpTransport,
        *,
        endpoint: str = DEFAULT_PARALLEL_MCP_ENDPOINT,
        model_name: str = DEFAULT_PARALLEL_MCP_MODEL_NAME,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time_sleep,
    ) -> None:
        self._transport = transport
        self._endpoint = endpoint
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def _build_request(self, query: str) -> dict:
        normalized_query = " ".join(query.split())
        session_id = str(uuid4())

        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "web_search",
                "arguments": {
                    "objective": f"Find accurate and up-to-date information about: {normalized_query}",
                    "search_queries": [
                        normalized_query,
                        f"latest {normalized_query}",
                        f"{normalized_query} official",
                    ],
                    "session_id": session_id,
                    "model_name": self._model_name,
                },
            },
        }

    def search(
        self,
        query: str,
        *,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        """
        Perform a web search through Parallel's MCP endpoint.

        Raises:
            InvalidSearchQueryError:
                If `query` is empty or `max_results` is not positive.

            WebSearchTimeoutError:
                If every attempt times out.

            WebSearchNetworkError:
                If every attempt fails for another network reason, the
                response is malformed, or the JSON-RPC payload is invalid.
        """

        validate_search_arguments(query, max_results)

        request_body = self._build_request(query)

        body_bytes = json.dumps(request_body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        logger.debug("========== PARALLEL MCP SEARCH REQUEST ==========")
        logger.debug("Query: %s", query)
        logger.debug("Endpoint: %s", self._endpoint)
        logger.debug("========== REQUEST BODY ==========")
        logger.debug("Body: %s", body_bytes)
        logger.debug("========================================")

        response = fetch_with_retry(
            self._transport,
            self._endpoint,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            sleep=self._sleep,
            method="POST",
            data=body_bytes,
            headers=headers,
        )
        raise_if_http_error(response, provider_name="Parallel MCP")

        decoded_text = decode_body(response)

        try:
            rpc_payload = json.loads(decoded_text)
        except json.JSONDecodeError as ex:
            raise WebSearchNetworkError(
                "Parallel MCP returned malformed JSON."
            ) from ex

        if not isinstance(rpc_payload, dict):
            raise WebSearchNetworkError(
                "Parallel MCP returned an invalid JSON-RPC response."
            )

        result = rpc_payload.get("result")
        if not isinstance(result, dict):
            raise WebSearchNetworkError(
                "Parallel MCP returned an invalid JSON-RPC response."
            )

        structured_content = result.get("structuredContent")
        if isinstance(structured_content, dict):
            payload = structured_content
        else:
            raw_content = result.get("content")
            if not isinstance(raw_content, list) or not raw_content:
                raise WebSearchNetworkError(
                    "Parallel MCP returned an invalid JSON-RPC response."
                )

            first_content = raw_content[0]
            if not isinstance(first_content, dict):
                raise WebSearchNetworkError(
                    "Parallel MCP returned an invalid JSON-RPC response."
                )

            embedded_text = first_content.get("text")
            if not isinstance(embedded_text, str):
                raise WebSearchNetworkError(
                    "Parallel MCP returned an invalid JSON-RPC response."
                )

            try:
                payload = json.loads(embedded_text)
            except json.JSONDecodeError as ex:
                raise WebSearchNetworkError(
                    "Parallel MCP returned malformed JSON."
                ) from ex

        if not isinstance(payload, dict):
            raise WebSearchNetworkError(
                "Parallel MCP returned an invalid JSON-RPC response."
            )

        results_payload = payload.get("results")
        if not isinstance(results_payload, list):
            raise WebSearchNetworkError(
                "Parallel MCP returned an invalid JSON-RPC response."
            )

        parsed_results: list[SearchResult] = []
        for item in results_payload:
            if not isinstance(item, dict):
                continue

            title = item.get("title")
            url = item.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                continue

            excerpts = item.get("excerpts")
            snippet: str | None = None
            if isinstance(excerpts, list) and excerpts:
                first_excerpt = excerpts[0]
                if isinstance(first_excerpt, str):
                    snippet = first_excerpt

            parsed_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    display_url=None,
                )
            )

        logger.debug("========== PARALLEL MCP SEARCH PARSER ==========")
        logger.debug("Query: %s", query)
        logger.debug("Endpoint: %s", self._endpoint)
        logger.debug("Response Size: %d bytes", len(decoded_text))
        logger.debug("Parsed Results: %d", len(parsed_results))
        logger.debug("========================================")

        return tuple(parsed_results[:max_results])
