"""
PARIKA Expense Tool - Period Resolution

Defines every period PARIKA's Expense Management supports (day, week,
month, year, custom range, first/second half of a month) as one
deterministic, documented resolution function, per
`docs/architecture/adr/0003-expense-management.md`, Decision 4.

A week is Monday-Sunday. A "half of a month" is defined exactly as
the requirement specifies:

    First half:  day 1 through day 15 (inclusive)
    Second half: day 16 through the month's last day (inclusive)

Every `Period` is an inclusive `[start, end]` date range.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from .exceptions import ExpenseInvalidRequestError


class PeriodKeyword(StrEnum):
    """
    Every period keyword a Tool argument may supply. `CUSTOM` requires
    an explicit `start_date`/`end_date` instead of `year`/`month`.
    """

    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    THIS_YEAR = "this_year"
    LAST_YEAR = "last_year"
    FIRST_HALF_MONTH = "first_half_month"
    SECOND_HALF_MONTH = "second_half_month"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True, kw_only=True)
class Period:
    """
    An inclusive `[start, end]` date range with a human-readable label.
    """

    start: date
    end: date
    label: str

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ExpenseInvalidRequestError(
                "A period's end date cannot be before its start date."
            )

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def month_range(year: int, month: int) -> Period:
    """The full calendar month `[year]-[month]-01, last day]`."""

    first_day = date(year, month, 1)
    last_day_number = monthrange(year, month)[1]
    last_day = date(year, month, last_day_number)

    return Period(start=first_day, end=last_day, label=first_day.strftime("%B %Y"))


def first_half_of_month(year: int, month: int) -> Period:
    """Day 1 through day 15 (inclusive) of `year`-`month`."""

    first_day = date(year, month, 1)

    return Period(
        start=first_day,
        end=date(year, month, 15),
        label=f"1-15 {first_day.strftime('%B %Y')}",
    )


def second_half_of_month(year: int, month: int) -> Period:
    """Day 16 through the month's last day (inclusive)."""

    last_day_number = monthrange(year, month)[1]
    first_day = date(year, month, 1)

    return Period(
        start=date(year, month, 16),
        end=date(year, month, last_day_number),
        label=f"16-{last_day_number} {first_day.strftime('%B %Y')}",
    )


def week_range(day: date) -> Period:
    """The Monday-Sunday week containing `day`."""

    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)

    return Period(start=start, end=end, label=f"week of {start.isoformat()}")


def year_range(year: int) -> Period:
    return Period(start=date(year, 1, 1), end=date(year, 12, 31), label=str(year))


def resolve_period(
    keyword: PeriodKeyword | str,
    *,
    today: date,
    year: int | None = None,
    month: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Period:
    """
    Resolve a `PeriodKeyword` (optionally scoped to a specific
    `year`/`month`) into a concrete `Period`.

    Args:
        keyword:
            One of `PeriodKeyword`'s values.

        today:
            The caller's notion of "today", used by every
            today-relative keyword.

        year, month:
            Optional explicit scope for month/half/year-based
            keywords (e.g. `THIS_MONTH` with `year=2026, month=7` asks
            for July 2026, not the current month). Ignored by
            `TODAY`/`YESTERDAY`/`THIS_WEEK`/`LAST_WEEK`.

        start_date, end_date:
            Required, and only used, when `keyword` is `CUSTOM`.

    Raises:
        ExpenseInvalidRequestError:
            If `keyword` is `CUSTOM` without both dates, or is not a
            recognized `PeriodKeyword` value.
    """

    resolved_keyword = PeriodKeyword(keyword)

    if resolved_keyword is PeriodKeyword.CUSTOM:
        if start_date is None or end_date is None:
            raise ExpenseInvalidRequestError(
                "period 'custom' requires both start_date and end_date."
            )
        return Period(
            start=start_date,
            end=end_date,
            label=f"{start_date.isoformat()} to {end_date.isoformat()}",
        )

    if resolved_keyword is PeriodKeyword.TODAY:
        return Period(start=today, end=today, label="today")

    if resolved_keyword is PeriodKeyword.YESTERDAY:
        yesterday = today - timedelta(days=1)
        return Period(start=yesterday, end=yesterday, label="yesterday")

    if resolved_keyword is PeriodKeyword.THIS_WEEK:
        return week_range(today)

    if resolved_keyword is PeriodKeyword.LAST_WEEK:
        this_week = week_range(today)
        return week_range(this_week.start - timedelta(days=7))

    if resolved_keyword is PeriodKeyword.THIS_YEAR:
        return year_range(year if year is not None else today.year)

    if resolved_keyword is PeriodKeyword.LAST_YEAR:
        return year_range((year if year is not None else today.year) - 1)

    resolved_year = year if year is not None else today.year
    resolved_month = month if month is not None else today.month

    if resolved_keyword is PeriodKeyword.THIS_MONTH:
        return month_range(resolved_year, resolved_month)

    if resolved_keyword is PeriodKeyword.LAST_MONTH:
        if year is None and month is None:
            base = date(today.year, today.month, 1) - timedelta(days=1)
        else:
            base = date(resolved_year, resolved_month, 1) - timedelta(days=1)
        return month_range(base.year, base.month)

    if resolved_keyword is PeriodKeyword.FIRST_HALF_MONTH:
        return first_half_of_month(resolved_year, resolved_month)

    if resolved_keyword is PeriodKeyword.SECOND_HALF_MONTH:
        return second_half_of_month(resolved_year, resolved_month)

    raise ExpenseInvalidRequestError(f"Unsupported period keyword: {keyword!r}")
