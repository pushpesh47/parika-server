"""
Unit tests for `parika.providers.ollama.transparency`.
"""

from __future__ import annotations

import logging

import pytest

from parika.providers.ollama.transparency import (
    log_execution_completed,
    log_native_tool_calls_received,
    log_sending_request,
    log_streaming_final_response,
    log_streaming_started,
    log_tool_requested,
)

_LOGGER = logging.getLogger("test.transparency")


@pytest.fixture(autouse=True)
def _debug_level(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.DEBUG, logger=_LOGGER.name):
        yield


class TestLogSendingRequest:
    def test_includes_advertised_tool_names(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log_sending_request(
            _LOGGER,
            model_id="m1",
            endpoint="/api/chat",
            streaming=False,
            tool_names=["web_search", "get_current_datetime"],
        )

        assert "advertised_tools" in caplog.text
        assert "web_search" in caplog.text
        assert "get_current_datetime" in caplog.text

    def test_omits_tools_section_when_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log_sending_request(
            _LOGGER, model_id="m1", endpoint="/api/generate", streaming=True
        )

        assert "advertised_tools" not in caplog.text


class TestLogNativeToolCallsReceived:
    def test_logs_count(self, caplog: pytest.LogCaptureFixture) -> None:
        log_native_tool_calls_received(_LOGGER, "m1", 2)

        assert "count=2" in caplog.text


class TestLogExecutionCompleted:
    def test_includes_tool_calls_when_provided(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log_execution_completed(_LOGGER, "m1", 123.456, tool_calls=2)

        assert "tool_calls=2" in caplog.text

    def test_omits_tool_calls_when_absent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log_execution_completed(_LOGGER, "m1", 123.456)

        assert "tool_calls" not in caplog.text


class TestOtherLoggingHelpers:
    def test_log_streaming_started(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log_streaming_started(_LOGGER, "m1")

        assert "Streaming started" in caplog.text

    def test_log_streaming_final_response(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        log_streaming_final_response(_LOGGER, "m1", 42)

        assert "length=42" in caplog.text

    def test_log_tool_requested(self, caplog: pytest.LogCaptureFixture) -> None:
        log_tool_requested(_LOGGER, "m1", ["web_search"])

        assert "web_search" in caplog.text
