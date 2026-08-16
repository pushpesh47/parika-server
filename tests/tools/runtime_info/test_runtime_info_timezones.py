"""
Unit tests for `parika.tools.runtime_info.timezones`.
"""

from __future__ import annotations

import pytest
from zoneinfo import ZoneInfo

from parika.tools.runtime_info.exceptions import UnknownTimezoneError
from parika.tools.runtime_info.timezones import resolve_timezone


class TestResolveTimezone:
    def test_none_resolves_to_utc(self) -> None:
        assert resolve_timezone(None) == ZoneInfo("UTC")

    def test_empty_string_resolves_to_utc(self) -> None:
        assert resolve_timezone("") == ZoneInfo("UTC")

    def test_resolves_ist_abbreviation_to_india(self) -> None:
        assert resolve_timezone("IST") == ZoneInfo("Asia/Kolkata")

    def test_abbreviation_is_case_insensitive(self) -> None:
        assert resolve_timezone("ist") == ZoneInfo("Asia/Kolkata")

    def test_resolves_utc_abbreviation(self) -> None:
        assert resolve_timezone("UTC") == ZoneInfo("UTC")

    def test_resolves_full_iana_name(self) -> None:
        assert resolve_timezone("Asia/Kolkata") == ZoneInfo("Asia/Kolkata")

    def test_resolves_est_abbreviation(self) -> None:
        assert resolve_timezone("EST") == ZoneInfo("America/New_York")

    def test_raises_for_unknown_timezone(self) -> None:
        with pytest.raises(UnknownTimezoneError):
            resolve_timezone("Not/A/Real/Zone")

    def test_strips_whitespace(self) -> None:
        assert resolve_timezone("  IST  ") == ZoneInfo("Asia/Kolkata")
