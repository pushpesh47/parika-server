"""
PARIKA Expense Tool - Money

Deterministic, exact monetary arithmetic for the Expense Management
capability.

Every persisted and aggregated amount is represented as an integer
number of "minor units" of its currency (e.g. paise for INR, cents
for USD: 1 major unit = 100 minor units) rather than as a
floating-point number. Storage (`storage.py`) and every SQL
aggregation (`SUM`/`GROUP BY`) therefore only ever add/subtract exact
Python `int` values - never binary floating point - so totals,
differences, and category/period aggregates are always exact. See
`docs/architecture/adr/0003-expense-management.md`, Decision 1.

`Decimal` is used only at the boundary: converting a caller-supplied
amount (which may arrive as `str`, `int`, `float`, or `Decimal`) into
exact minor units, and converting minor units back into a
human-readable amount string for display. Once inside the domain
layer, everything is plain integer arithmetic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .exceptions import ExpenseInvalidRequestError

MINOR_UNITS_PER_MAJOR_UNIT = 100
"""Every currency this module supports uses a 2-decimal-place minor unit (paise/cents)."""


def to_minor_units(amount: object) -> int:
    """
    Convert a caller-supplied amount into exact integer minor units.

    Args:
        amount:
            A `Decimal`, `int`, `float`, or numeric `str`. Booleans
            are rejected explicitly (`bool` is a `int` subclass in
            Python and would otherwise silently succeed as `0`/`1`).

    Returns:
        The amount, rounded to the nearest minor unit
        (`ROUND_HALF_UP`) only when the input has more precision than
        the currency supports (e.g. `19.999` -> 2000 minor units).

    Raises:
        ExpenseInvalidRequestError:
            If `amount` is not a finite, well-formed number.
    """

    if isinstance(amount, bool):
        raise ExpenseInvalidRequestError(
            "amount must be a number, not a boolean."
        )

    try:
        decimal_amount = (
            amount if isinstance(amount, Decimal) else Decimal(str(amount))
        )
    except (InvalidOperation, ValueError, TypeError) as ex:
        raise ExpenseInvalidRequestError(
            f"amount {amount!r} is not a valid number."
        ) from ex

    if not decimal_amount.is_finite():
        raise ExpenseInvalidRequestError("amount must be a finite number.")

    scaled = (decimal_amount * MINOR_UNITS_PER_MAJOR_UNIT).to_integral_value(
        rounding=ROUND_HALF_UP
    )

    return int(scaled)


def from_minor_units(minor_units: int) -> Decimal:
    """
    Convert exact integer minor units back into a 2-decimal-place
    `Decimal` amount, suitable for display or JSON serialization
    (always via `str()`, never `float()`).
    """

    return (Decimal(minor_units) / MINOR_UNITS_PER_MAJOR_UNIT).quantize(
        Decimal("0.01")
    )


def validate_currency_code(value: object, *, default: str) -> str:
    """
    Validate and normalize a 3-letter ISO 4217 currency code.

    Args:
        value:
            The caller-supplied currency code, or `None`/blank to
            fall back to `default`.

        default:
            The module's configured default currency (see
            `config.py`), used when `value` is omitted.

    Raises:
        ExpenseInvalidRequestError:
            If the resolved code is not exactly 3 alphabetic
            characters.
    """

    candidate = value if isinstance(value, str) and value.strip() else default
    normalized = candidate.strip().upper()

    if len(normalized) != 3 or not normalized.isalpha():
        raise ExpenseInvalidRequestError(
            f"currency {value!r} must be a 3-letter ISO 4217 code, e.g. 'INR'."
        )

    return normalized
