"""
Unit tests for period resolution (`parika/tools/expense/periods.py`).
"""

from __future__ import annotations

from datetime import date

import pytest

from parika.tools.expense.exceptions import ExpenseInvalidRequestError
from parika.tools.expense.periods import (
    Period,
    PeriodKeyword,
    first_half_of_month,
    resolve_period,
    second_half_of_month,
    week_range,
)

TODAY = date(2026, 8, 9)  # a Sunday


class TestHalfMonth:
    def test_first_half_is_day_1_through_15(self) -> None:
        period = first_half_of_month(2026, 8)
        assert period.start == date(2026, 8, 1)
        assert period.end == date(2026, 8, 15)

    def test_second_half_is_day_16_through_last_day(self) -> None:
        period = second_half_of_month(2026, 8)
        assert period.start == date(2026, 8, 16)
        assert period.end == date(2026, 8, 31)

    def test_second_half_handles_short_february(self) -> None:
        period = second_half_of_month(2026, 2)
        assert period.end == date(2026, 2, 28)


class TestWeekRange:
    def test_week_is_monday_to_sunday(self) -> None:
        period = week_range(TODAY)
        assert period.start.weekday() == 0
        assert period.end.weekday() == 6
        assert period.start == date(2026, 8, 3)
        assert period.end == date(2026, 8, 9)


class TestResolvePeriod:
    def test_today(self) -> None:
        period = resolve_period(PeriodKeyword.TODAY, today=TODAY)
        assert period.start == period.end == TODAY

    def test_yesterday(self) -> None:
        period = resolve_period(PeriodKeyword.YESTERDAY, today=TODAY)
        assert period.start == period.end == date(2026, 8, 8)

    def test_this_week(self) -> None:
        period = resolve_period(PeriodKeyword.THIS_WEEK, today=TODAY)
        assert period.start == date(2026, 8, 3)
        assert period.end == date(2026, 8, 9)

    def test_last_week(self) -> None:
        period = resolve_period(PeriodKeyword.LAST_WEEK, today=TODAY)
        assert period.start == date(2026, 7, 27)
        assert period.end == date(2026, 8, 2)

    def test_this_month(self) -> None:
        period = resolve_period(PeriodKeyword.THIS_MONTH, today=TODAY)
        assert period.start == date(2026, 8, 1)
        assert period.end == date(2026, 8, 31)

    def test_last_month(self) -> None:
        period = resolve_period(PeriodKeyword.LAST_MONTH, today=TODAY)
        assert period.start == date(2026, 7, 1)
        assert period.end == date(2026, 7, 31)

    def test_last_month_across_year_boundary(self) -> None:
        period = resolve_period(PeriodKeyword.LAST_MONTH, today=date(2026, 1, 15))
        assert period.start == date(2025, 12, 1)
        assert period.end == date(2025, 12, 31)

    def test_this_year(self) -> None:
        period = resolve_period(PeriodKeyword.THIS_YEAR, today=TODAY)
        assert period.start == date(2026, 1, 1)
        assert period.end == date(2026, 12, 31)

    def test_last_year(self) -> None:
        period = resolve_period(PeriodKeyword.LAST_YEAR, today=TODAY)
        assert period.start == date(2025, 1, 1)
        assert period.end == date(2025, 12, 31)

    def test_this_month_with_explicit_year_month(self) -> None:
        period = resolve_period(
            PeriodKeyword.THIS_MONTH, today=TODAY, year=2026, month=7
        )
        assert period.start == date(2026, 7, 1)
        assert period.end == date(2026, 7, 31)

    def test_first_half_month_keyword(self) -> None:
        period = resolve_period(
            PeriodKeyword.FIRST_HALF_MONTH, today=TODAY, year=2026, month=8
        )
        assert period.start == date(2026, 8, 1)
        assert period.end == date(2026, 8, 15)

    def test_second_half_month_keyword(self) -> None:
        period = resolve_period(
            PeriodKeyword.SECOND_HALF_MONTH, today=TODAY, year=2026, month=8
        )
        assert period.start == date(2026, 8, 16)
        assert period.end == date(2026, 8, 31)

    def test_custom_requires_both_dates(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            resolve_period(PeriodKeyword.CUSTOM, today=TODAY, start_date=TODAY)

    def test_custom_with_both_dates(self) -> None:
        period = resolve_period(
            PeriodKeyword.CUSTOM,
            today=TODAY,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 7),
        )
        assert period.start == date(2026, 8, 1)
        assert period.end == date(2026, 8, 7)

    def test_invalid_keyword_raises(self) -> None:
        with pytest.raises(ValueError):
            resolve_period("not-a-real-period", today=TODAY)


class TestPeriodInvariant:
    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            Period(start=date(2026, 8, 10), end=date(2026, 8, 1), label="bad")

    def test_contains(self) -> None:
        period = Period(start=date(2026, 8, 1), end=date(2026, 8, 15), label="l")
        assert period.contains(date(2026, 8, 10))
        assert not period.contains(date(2026, 8, 20))
