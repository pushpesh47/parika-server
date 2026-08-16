"""
PARIKA Ollama Provider - Execution Transparency Logging

Small DEBUG-level logging helpers used throughout the request/response
lifecycle (`driver.py`, `chat_loop.py`, `tool_calling.py`) so every
stage of a request - sending it, streaming, tool calls, and
completion - is observable without needing to instrument each call
site with an inline multi-line `logger.debug(...)` call. Kept in one
place purely to keep those modules focused on orchestration (see
`PARIKA_Core_Coding_Standards.md` - File Size Guidelines).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence


def log_sending_request(
    logger: logging.Logger,
    *,
    model_id: str,
    endpoint: str,
    streaming: bool,
    tool_names: Sequence[str] | None = None,
) -> None:
    """
    Log a request about to be sent, including exactly which tools
    (advertised capabilities) it offers the model, if any.
    """

    if tool_names is None:
        logger.debug(
            "Sending request: model=%s endpoint=%s streaming=%s",
            model_id,
            endpoint,
            streaming,
        )
    else:
        logger.debug(
            "Sending request: model=%s endpoint=%s streaming=%s "
            "advertised_tools=%s",
            model_id,
            endpoint,
            streaming,
            list(tool_names),
        )


def log_native_tool_calls_received(
    logger: logging.Logger,
    model_id: str,
    count: int,
) -> None:
    """
    Log how many tool calls Ollama's native `tool_calls` field
    reported, before any text-based fallback recovery is attempted -
    useful for distinguishing "the model never tried" from "the model
    tried but its template leaked the call as text" (see
    `text_tool_calls.py`).
    """

    logger.debug(
        "Native tool calls received: model=%s count=%d", model_id, count
    )


def log_streaming_started(logger: logging.Logger, model_id: str) -> None:
    logger.debug("Streaming started: model=%s", model_id)


def log_streaming_final_response(
    logger: logging.Logger,
    model_id: str,
    length: int,
) -> None:
    logger.debug(
        "Streaming final response: model=%s length=%d", model_id, length
    )


def log_tool_requested(
    logger: logging.Logger,
    model_id: str,
    tool_names: Sequence[str],
) -> None:
    logger.debug("Tool requested: model=%s tools=%s", model_id, list(tool_names))


def log_execution_completed(
    logger: logging.Logger,
    model_id: str,
    total_time_ms: float,
    *,
    tool_calls: int | None = None,
) -> None:
    if tool_calls is None:
        logger.debug(
            "Execution completed: model=%s total_time_ms=%.3f",
            model_id,
            total_time_ms,
        )
    else:
        logger.debug(
            "Execution completed: model=%s tool_calls=%d total_time_ms=%.3f",
            model_id,
            tool_calls,
            total_time_ms,
        )
