"""
PARIKA Expense Tool - Domain Model

Defines the immutable `Expense` domain object. See
`docs/architecture/adr/0003-expense-management.md` for the rationale
behind every field, in particular:

- `amount_minor` is an exact integer (never a float) - see `money.py`.
- `expense_date` is when the expense actually occurred, deliberately
  distinct from `created_at` (when the record was written). Updating
  an expense's date never touches `created_at`; only `updated_at`
  changes.
- `category` is always optional and never silently invented: the
  original `item`/description is always preserved verbatim regardless
  of what category (if any) is inferred for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .money import from_minor_units

DEFAULT_EXPENSE_CURRENCY = "INR"
"""
PARIKA's Expense Management defaults to INR/₹ for this personal
tracker, per the requirement; `[expense].default_currency` in
`config/defaults.toml` overrides this.
"""

DEFAULT_EXPENSE_CATEGORIES: tuple[str, ...] = (
    "Food",
    "Groceries",
    "Medicine",
    "Transport",
    "Shopping",
    "Bills",
    "Education",
    "Investment",
    "Personal",
    "Household",
    "Other",
)
"""
A lightweight, *suggested* taxonomy only - advertised to the model via
the Tool Affordance Contract (`manifest.py`) so category inference has
a sensible default vocabulary. `Expense.category` is a free string,
never a validated enum: any value is accepted and stored, and `None`
(uncategorized) is always valid. See this package's own module
docstring on why `Investment` (e.g. a SIP) is a category, not a
distinct transaction type - PARIKA does not otherwise model financial
transaction types.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Expense:
    """
    Immutable record of one personal expense.
    """

    id: str
    amount_minor: int
    currency: str
    item: str
    category: str | None
    expense_date: date
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def amount(self) -> Decimal:
        """Exact 2-decimal-place amount, in major units (e.g. rupees)."""

        return from_minor_units(self.amount_minor)

    def to_dict(self) -> dict[str, object]:
        """
        Structured, JSON-serializable representation, used by every
        Tool response and API response - amounts are always `str()`
        (never `float()`), so a JSON client never reintroduces binary
        floating-point error.
        """

        return {
            "id": self.id,
            "amount": str(self.amount),
            "currency": self.currency,
            "item": self.item,
            "category": self.category,
            "expense_date": self.expense_date.isoformat(),
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
