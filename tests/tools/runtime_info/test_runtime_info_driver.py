"""
Unit tests for `parika.tools.runtime_info.driver`.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.tools.runtime_info.driver import RuntimeInfoToolDriver
from parika.tools.runtime_info.exceptions import UnknownTimezoneError


class TestRuntimeInfoToolDriver:
    def test_defaults_to_utc_when_no_timezone_supplied(self) -> None:
        driver = RuntimeInfoToolDriver()

        response = driver.execute(ToolRequest())

        assert response.result["timezone"] == "UTC"

    def test_resolves_ist_abbreviation(self) -> None:
        driver = RuntimeInfoToolDriver()

        response = driver.execute(
            ToolRequest(arguments={"timezone": "IST"})
        )

        assert response.result["timezone"] == "Asia/Kolkata"
        assert response.attributes["timezone"] == "Asia/Kolkata"

    def test_result_reflects_the_real_current_time(self) -> None:
        driver = RuntimeInfoToolDriver()

        before = datetime.now(ZoneInfo("UTC")).replace(microsecond=0)
        response = driver.execute(ToolRequest(arguments={"timezone": "UTC"}))
        after = datetime.now(ZoneInfo("UTC"))

        reported = datetime.fromisoformat(response.result["iso_datetime"])

        assert before <= reported <= after

    def test_result_contains_expected_keys(self) -> None:
        driver = RuntimeInfoToolDriver()

        response = driver.execute(ToolRequest())

        assert set(response.result) == {
            "date",
            "time",
            "weekday",
            "timezone",
            "utc_offset",
            "iso_datetime",
        }

    def test_raises_for_unknown_timezone(self) -> None:
        driver = RuntimeInfoToolDriver()

        with pytest.raises(UnknownTimezoneError):
            driver.execute(ToolRequest(arguments={"timezone": "Not/Real"}))

    def test_ignores_non_string_timezone_argument(self) -> None:
        driver = RuntimeInfoToolDriver()

        response = driver.execute(
            ToolRequest(arguments={"timezone": 12345})
        )

        assert response.result["timezone"] == "UTC"
