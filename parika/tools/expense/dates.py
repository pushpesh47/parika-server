"""
PARIKA Expense Tool - Deterministic Date Resolution

PARIKA has no existing shared natural-language date-parsing
infrastructure (Core/Interfaces resolve dates only via the standard
library `datetime`), so this module provides one small, deterministic,
fully-tested parser scoped to exactly the expressions the Expense
Management requirement lists: `today`, `yesterday`, `tomorrow`,
weekday names, `last <weekday>`, and absolute dates in ISO
(`2026-08-05`), `DD/MM/YYYY` (matching the user's own spreadsheet
convention), and `<day> <month name>[, <year>]` /
`<month name> <day>[, <year>]` forms.

This is a single ordered list of ordinary, testable parsing
strategies - not a growing pile of ad hoc string hacks scattered
through the codebase. It never guesses via an LLM: every recognized
phrase resolves to exactly one `date.date`, and anything unrecognized
raises `ExpenseInvalidRequestError` so the caller (Planner/the model)
can ask the user for clarification instead of silently picking a
wrong date.

The Expense Management requirement explicitly separates
"when the expense occurred" (`expense_date`, resolved here) from
"when the record was created" (`Expense.created_at`, always `now()`).
This module resolves only the former.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .exceptions import ExpenseInvalidRequestError

_WEEKDAY_NAMES: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_MONTH_NAMES: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_SLASH_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")
_DAY_MONTH_RE = re.compile(
    r"^(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\.?(?:,?\s+(\d{4}))?$"
)
_MONTH_DAY_RE = re.compile(
    r"^([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?$"
)


def parse_expense_date(text: str | None, *, today: date) -> date:
    """
    Resolve a natural-language or absolute date phrase into a
    concrete `date`.

    Args:
        text:
            The phrase to resolve. `None` or blank resolves to
            `today` (matches the requirement's "ambiguous input"
            example: an omitted date on `add_expense` defaults to
            today).

        today:
            The caller's notion of "today" (injected rather than
            read from the system clock here, so tests are
            deterministic).

    Returns:
        The resolved date.

    Raises:
        ExpenseInvalidRequestError:
            If `text` does not match any recognized form.
    """

    if text is None:
        return today

    normalized = text.strip().lower()

    if not normalized:
        return today

    if normalized in ("today", "now"):
        return today

    if normalized == "yesterday":
        return today - timedelta(days=1)

    if normalized == "tomorrow":
        return today + timedelta(days=1)

    is_last = False
    remainder = normalized

    if remainder.startswith("last "):
        is_last = True
        remainder = remainder[len("last "):].strip()
    elif remainder.startswith("this "):
        remainder = remainder[len("this "):].strip()
    elif remainder.startswith("on "):
        remainder = remainder[len("on "):].strip()

    if remainder in _WEEKDAY_NAMES:
        return _resolve_weekday(remainder, today=today, is_last=is_last)

    iso_date = _try_parse_iso(remainder)
    if iso_date is not None:
        return iso_date

    slash_date = _try_parse_slash(remainder)
    if slash_date is not None:
        return slash_date

    day_month_match = _DAY_MONTH_RE.match(remainder)
    if day_month_match is not None:
        day_str, month_str, year_str = day_month_match.groups()
        return _build_date_from_day_month(day_str, month_str, year_str, today)

    month_day_match = _MONTH_DAY_RE.match(remainder)
    if month_day_match is not None:
        month_str, day_str, year_str = month_day_match.groups()
        return _build_date_from_day_month(day_str, month_str, year_str, today)

    raise ExpenseInvalidRequestError(
        f"Could not understand the date '{text}'. Try a form like "
        "'today', 'yesterday', 'Monday', '5 August', '05/08/2026', "
        "or '2026-08-05'."
    )


def _resolve_weekday(name: str, *, today: date, is_last: bool) -> date:
    target_weekday = _WEEKDAY_NAMES[name]
    days_since = (today.weekday() - target_weekday) % 7
    resolved = today - timedelta(days=days_since)

    if is_last:
        resolved -= timedelta(days=7)

    return resolved


def _try_parse_iso(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _try_parse_slash(text: str) -> date | None:
    match = _SLASH_DATE_RE.match(text)

    if match is None:
        return None

    day_str, month_str, year_str = match.groups()
    year = int(year_str)

    if len(year_str) == 2:
        year += 2000

    try:
        return date(year, int(month_str), int(day_str))
    except ValueError as ex:
        raise ExpenseInvalidRequestError(
            f"'{text}' is not a valid DD/MM/YYYY date."
        ) from ex


def _build_date_from_day_month(
    day_str: str, month_str: str, year_str: str | None, today: date
) -> date:
    month = _MONTH_NAMES.get(month_str)

    if month is None:
        raise ExpenseInvalidRequestError(f"'{month_str}' is not a recognized month name.")

    day = int(day_str)
    year = int(year_str) if year_str is not None else today.year

    try:
        resolved = date(year, month, day)
    except ValueError as ex:
        raise ExpenseInvalidRequestError(
            f"'{day_str} {month_str}' is not a valid date."
        ) from ex

    # When no year was given and the resolved date would fall in the
    # future, assume the caller meant the most recent occurrence
    # (last year) rather than a future expense - expenses are, by
    # definition, things that already happened.
    if year_str is None and resolved > today:
        resolved = date(year - 1, month, day)

    return resolved
