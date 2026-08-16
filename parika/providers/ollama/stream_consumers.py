"""
PARIKA Ollama Provider - Streaming Response Consumers

Pure functions that consume an iterator of NDJSON chunks already
produced by `OllamaTransport.stream_lines()`, invoking a streaming
callback per content fragment and returning the merged final chunk.
Kept separate from `driver.py` so the driver itself stays focused on
orchestration (see `PARIKA_Core_Coding_Standards.md` - File Size
Guidelines).
"""

from __future__ import annotations
import json
from collections.abc import Callable, Iterable
from typing import Any

from .exceptions import OllamaResponseError


def consume_generate_stream(
    chunks: Iterable[dict[str, Any]],
    *,
    on_token: Callable[[str], None],
) -> dict[str, Any]:
    """
    Consume a streamed `/api/generate` response.

    Args:
        chunks:
            NDJSON chunks, oldest first, as yielded by
            `OllamaTransport.stream_lines()`.

        on_token:
            Callback invoked once per non-empty `response` fragment.

    Returns:
        The final chunk (the one with `done: true`), with its
        `response` field replaced by the full accumulated text.

    Raises:
        OllamaResponseError:
            If the stream ends without a final chunk.
    """

    final_chunk: dict[str, Any] | None = None
    accumulated: list[str] = []

    for chunk in chunks:
        fragment = chunk.get("response")

        if fragment:
            accumulated.append(fragment)
            on_token(fragment)

        if chunk.get("done"):
            final_chunk = chunk

    if final_chunk is None:
        raise OllamaResponseError(
            "Ollama's streamed /api/generate response ended without "
            "a final chunk."
        )

    final_chunk = dict(final_chunk)
    final_chunk["response"] = "".join(accumulated)

    return final_chunk


def consume_chat_stream(
    chunks: Iterable[dict[str, Any]],
    *,
    on_token: Callable[[str], None],
) -> dict[str, Any]:
    """
    Consume a streamed `/api/chat` response.

    Ollama reports tool calls only on the final streamed chunk, with
    empty content fragments for every preceding chunk of a
    tool-calling turn, so `on_token` is effectively only invoked for
    genuine, directly displayable assistant text.

    Args:
        chunks:
            NDJSON chunks, oldest first, as yielded by
            `OllamaTransport.stream_lines()`.

        on_token:
            Callback invoked once per non-empty `message.content`
            fragment.

    Returns:
        The final chunk, with its `message.content` field replaced by
        the full accumulated text.

    Raises:
        OllamaResponseError:
            If the stream ends without a final chunk.
    """

    final_chunk: dict[str, Any] | None = None
    accumulated: list[str] = []
    accumulated_tool_calls: list[dict[str, Any]] = []

    for chunk in chunks:
        message_chunk = chunk.get("message")
        message_chunk = message_chunk if isinstance(message_chunk, dict) else {}

        tool_calls = message_chunk.get("tool_calls")
        if isinstance(tool_calls, list):
            accumulated_tool_calls.extend(tool_calls)

        fragment = message_chunk.get("content")

        if fragment:
            accumulated.append(fragment)
            on_token(fragment)

        if chunk.get("done"):
            final_chunk = chunk

    if final_chunk is None:
        raise OllamaResponseError(
            "Ollama's streamed /api/chat response ended without a "
            "final chunk."
        )

    final_chunk = dict(final_chunk)
    final_message = dict(final_chunk.get("message") or {})

    final_message["content"] = "".join(accumulated) or final_message.get(
        "content", ""
    )

    if accumulated_tool_calls:
        final_message["tool_calls"] = accumulated_tool_calls

    final_chunk["message"] = final_message

    return final_chunk
