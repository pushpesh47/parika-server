"""
Unit tests for exact money conversion (`parika/tools/expense/money.py`).
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

from decimal import Decimal

import pytest

from parika.tools.expense.exceptions import ExpenseInvalidRequestError
from parika.tools.expense.money import (
    from_minor_units,
    to_minor_units,
    validate_currency_code,
)


class TestToMinorUnits:
    def test_integer_amount(self) -> None:
        assert to_minor_units(2000) == 200000

    def test_string_amount(self) -> None:
        assert to_minor_units("2000") == 200000

    def test_decimal_amount(self) -> None:
        assert to_minor_units(Decimal("19.99")) == 1999

    def test_float_amount_rounds_to_nearest_minor_unit(self) -> None:
        assert to_minor_units(19.999) == 2000

    def test_rejects_boolean(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            to_minor_units(True)

    def test_rejects_non_numeric_string(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            to_minor_units("not-a-number")

    def test_rejects_infinite(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            to_minor_units(Decimal("Infinity"))


class TestFromMinorUnits:
    def test_round_trip(self) -> None:
        assert from_minor_units(200000) == Decimal("2000.00")

    def test_exactness_across_many_additions(self) -> None:
        # 3 * 33.33 = 99.99 exactly, in minor units - never 99.99000000000001.
        total = to_minor_units("33.33") * 3
        assert from_minor_units(total) == Decimal("99.99")


class TestValidateCurrencyCode:
    def test_uses_default_when_omitted(self) -> None:
        assert validate_currency_code(None, default="INR") == "INR"

    def test_normalizes_case(self) -> None:
        assert validate_currency_code("inr", default="INR") == "INR"

    def test_rejects_wrong_length(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            validate_currency_code("US", default="INR")

    def test_rejects_non_alphabetic(self) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            validate_currency_code("US1", default="INR")
