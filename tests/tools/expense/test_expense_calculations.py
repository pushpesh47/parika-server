"""
Unit tests for deterministic comparison math
(`parika/tools/expense/calculations.py`).
"""

from __future__ import annotations

from parika.tools.expense.calculations import (
    PeriodComparisonSide,
    build_category_breakdown,
    compare_totals,
)


class TestCompareTotals:
    def test_increase(self) -> None:
        current = PeriodComparisonSide(label="August", total_minor=150000, count=3)
        previous = PeriodComparisonSide(label="July", total_minor=100000, count=2)

        comparison = compare_totals(current, previous, category_breakdown={})

        assert comparison.difference_minor == 50000
        assert comparison.percentage_change == 50.0
        assert comparison.direction == "increased"
        assert comparison.note is None

    def test_decrease(self) -> None:
        current = PeriodComparisonSide(label="August", total_minor=50000, count=1)
        previous = PeriodComparisonSide(label="July", total_minor=100000, count=2)

        comparison = compare_totals(current, previous, category_breakdown={})

        assert comparison.difference_minor == -50000
        assert comparison.percentage_change == -50.0
        assert comparison.direction == "decreased"

    def test_unchanged_nonzero(self) -> None:
        current = PeriodComparisonSide(label="August", total_minor=100000, count=1)
        previous = PeriodComparisonSide(label="July", total_minor=100000, count=1)

        comparison = compare_totals(current, previous, category_breakdown={})

        assert comparison.difference_minor == 0
        assert comparison.percentage_change == 0.0
        assert comparison.direction == "unchanged"

    def test_zero_to_zero_is_unchanged_at_zero_percent(self) -> None:
        current = PeriodComparisonSide(label="August", total_minor=0, count=0)
        previous = PeriodComparisonSide(label="July", total_minor=0, count=0)

        comparison = compare_totals(current, previous, category_breakdown={})

        assert comparison.difference_minor == 0
        assert comparison.percentage_change == 0.0
        assert comparison.direction == "unchanged"
        assert comparison.note is None

    def test_zero_previous_with_positive_current_has_no_percentage_but_a_note(
        self,
    ) -> None:
        current = PeriodComparisonSide(label="August", total_minor=50000, count=1)
        previous = PeriodComparisonSide(label="July", total_minor=0, count=0)

        comparison = compare_totals(current, previous, category_breakdown={})

        assert comparison.difference_minor == 50000
        assert comparison.percentage_change is None
        assert comparison.direction == "increased"
        assert comparison.note is not None

    def test_never_raises_zero_division_error(self) -> None:
        current = PeriodComparisonSide(label="a", total_minor=0, count=0)
        previous = PeriodComparisonSide(label="b", total_minor=0, count=0)
        # Simply must not raise.
        compare_totals(current, previous, category_breakdown={})


class TestBuildCategoryBreakdown:
    def test_combines_and_sorts_by_absolute_difference(self) -> None:
        breakdown = build_category_breakdown(
            {"Groceries": 300000, "Medicine": 50000},
            {"Groceries": 100000, "Medicine": 50000, "Transport": 20000},
        )

        assert breakdown["Groceries"] == (300000, 100000, 200000)
        assert breakdown["Medicine"] == (50000, 50000, 0)
        assert breakdown["Transport"] == (0, 20000, -20000)
        # Largest absolute change first.
        assert list(breakdown.keys())[0] == "Groceries"
