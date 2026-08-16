"""
PARIKA Expense Tool - Deterministic Calculations

Every total, aggregate, and comparison the Expense Management
requirement asks for is computed here (or by `ExpenseStorage`'s SQL
aggregation, which this module composes) using exact integer minor
units - never by asking a model to add up retrieved text. See
`docs/architecture/adr/0003-expense-management.md`, Decision 2.

`percentage_change` is the one place a `float` appears: a percentage
is inherently a ratio for *display*, never a persisted or compared
monetary value, so ordinary float division is appropriate there -
`difference_minor` (the actual money) remains an exact `int`
throughout.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .model import Expense


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseSummary:
    """
    Deterministic summary of every expense matching one filter.
    """

    period_label: str
    currency: str
    total_minor: int
    count: int
    by_category: Mapping[str, int]
    by_item: Mapping[str, int]
    by_date: Mapping[str, int]
    largest: tuple[Expense, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class PeriodComparisonSide:
    """One side (current or previous) of a period comparison."""

    label: str
    total_minor: int
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class PeriodComparison:
    """
    Deterministic comparison between two periods (or two filtered
    slices, e.g. the same category across two months).
    """

    current: PeriodComparisonSide
    previous: PeriodComparisonSide
    difference_minor: int
    percentage_change: float | None
    direction: str
    note: str | None
    category_breakdown: Mapping[str, tuple[int, int, int]]
    """category -> (current_total_minor, previous_total_minor, difference_minor)"""


def compare_totals(
    current: PeriodComparisonSide,
    previous: PeriodComparisonSide,
    *,
    category_breakdown: Mapping[str, tuple[int, int, int]],
) -> PeriodComparison:
    """
    Deterministically compare two totals.

    Handles a zero-value comparison period explicitly, per the
    requirement: a zero-to-zero comparison is `"unchanged"` at 0%; a
    zero-to-positive comparison is `"increased"` with an explicit,
    documented `note` rather than a `ZeroDivisionError` or a nonsense
    infinite percentage.
    """

    difference = current.total_minor - previous.total_minor

    if previous.total_minor == 0:
        if current.total_minor == 0:
            percentage: float | None = 0.0
            direction = "unchanged"
            note = None
        else:
            percentage = None
            direction = "increased"
            note = (
                "The comparison period had no recorded expenses; "
                "percentage change is undefined."
            )
    else:
        percentage = round((difference / previous.total_minor) * 100, 2)

        if difference > 0:
            direction = "increased"
        elif difference < 0:
            direction = "decreased"
        else:
            direction = "unchanged"

        note = None

    return PeriodComparison(
        current=current,
        previous=previous,
        difference_minor=difference,
        percentage_change=percentage,
        direction=direction,
        note=note,
        category_breakdown=category_breakdown,
    )


def build_category_breakdown(
    current_by_category: Mapping[str, int],
    previous_by_category: Mapping[str, int],
) -> dict[str, tuple[int, int, int]]:
    """
    Combine two category->total_minor mappings (already computed by
    `ExpenseStorage.aggregate_by_category()`) into one
    category->(current, previous, difference) breakdown, sorted by
    the absolute size of the difference (largest change first).
    """

    categories = set(current_by_category) | set(previous_by_category)

    breakdown = {
        category: (
            current_by_category.get(category, 0),
            previous_by_category.get(category, 0),
            current_by_category.get(category, 0)
            - previous_by_category.get(category, 0),
        )
        for category in categories
    }

    return dict(
        sorted(breakdown.items(), key=lambda item: abs(item[1][2]), reverse=True)
    )
