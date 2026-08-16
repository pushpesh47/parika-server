"""
Unit tests for deterministic date resolution
(`parika/tools/expense/dates.py`).
"""

from __future__ import annotations

from datetime import date

import pytest

from parika.tools.expense.dates import parse_expense_date
from parika.tools.expense.exceptions import ExpenseInvalidRequestError

TODAY = date(2026, 8, 9)  # a Sunday


class TestRelativeKeywords:
    def test_none_defaults_to_today(self) -> None:
        assert parse_expense_date(None, today=TODAY) == TODAY

    def test_blank_defaults_to_today(self) -> None:
        assert parse_expense_date("   ", today=TODAY) == TODAY

    def test_today(self) -> None:
        assert parse_expense_date("today", today=TODAY) == TODAY

    def test_yesterday(self) -> None:
        assert parse_expense_date("yesterday", today=TODAY) == date(2026, 8, 8)

    def test_tomorrow(self) -> None:
        assert parse_expense_date("tomorrow", today=TODAY) == date(2026, 8, 10)

    def test_case_insensitive(self) -> None:
        assert parse_expense_date("YESTERDAY", today=TODAY) == date(2026, 8, 8)


class TestWeekdayNames:
    def test_bare_weekday_resolves_to_most_recent_occurrence_including_today(self) -> None:
        # TODAY is a Sunday.
        assert parse_expense_date("sunday", today=TODAY) == TODAY

    def test_bare_weekday_resolves_to_most_recent_past_occurrence(self) -> None:
        assert parse_expense_date("monday", today=TODAY) == date(2026, 8, 3)

    def test_last_weekday_goes_one_more_week_back(self) -> None:
        assert parse_expense_date("last monday", today=TODAY) == date(2026, 7, 27)

    def test_this_weekday_behaves_like_bare_weekday(self) -> None:
        assert parse_expense_date("this monday", today=TODAY) == date(2026, 8, 3)


class TestAbsoluteDates:
    def test_iso_date(self) -> None:
        assert parse_expense_date("2026-08-05", today=TODAY) == date(2026, 8, 5)

    def test_slash_date_is_day_month_year(self) -> None:
        assert parse_expense_date("01/08/2026", today=TODAY) == date(2026, 8, 1)

    def test_slash_date_two_digit_year(self) -> None:
        assert parse_expense_date("05/08/26", today=TODAY) == date(2026, 8, 5)

    def test_day_month_name(self) -> None:
        assert parse_expense_date("5 August", today=TODAY) == date(2026, 8, 5)

    def test_day_month_abbreviation(self) -> None:
        assert parse_expense_date("5 Aug", today=TODAY) == date(2026, 8, 5)

    def test_month_day_order(self) -> None:
        assert parse_expense_date("August 5", today=TODAY) == date(2026, 8, 5)

    def test_day_month_with_explicit_year(self) -> None:
        assert parse_expense_date("5 August 2025", today=TODAY) == date(2025, 8, 5)

    def test_day_month_without_year_in_the_future_assumes_last_year(self) -> None:
        # TODAY is 9 August 2026; "25 December" without a year would be
        # in the future, so it resolves to the most recent (last year's)
        # occurrence rather than a future expense.
        assert parse_expense_date("25 December", today=TODAY) == date(2025, 12, 25)

    def test_ordinal_suffix_is_tolerated(self) -> None:
        assert parse_expense_date("5th August", today=TODAY) == date(2026, 8, 5)


class TestInvalidInput:
    def test_unrecognized_phrase_raises(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            parse_expense_date("sometime last month-ish", today=TODAY)

    def test_unrecognized_month_name_raises(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            parse_expense_date("5 Augtober", today=TODAY)

    def test_invalid_calendar_date_raises(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            parse_expense_date("31 February 2026", today=TODAY)
