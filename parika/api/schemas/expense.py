"""
PARIKA API - Expense Schemas

Wire-format Pydantic schemas for the direct, structured
`/api/v1/expenses...` endpoints (the Web Client's CRUD/dashboard
surface - see `parika/api/handlers/expense.py`'s own module
docstring). Amounts are always `str` (never `float`), matching
`Expense.to_dict()`, so a JSON client never reintroduces binary
floating-point error into a value PARIKA computed exactly.
"""

from __future__ import annotations

from pydantic import Field

from .common import ApiModel


class ExpenseBody(ApiModel):
    id: str
    amount: str
    currency: str
    item: str
    category: str | None = None
    expense_date: str
    notes: str | None = None
    created_at: str
    updated_at: str


class ExpenseCreateRequestBody(ApiModel):
    amount: float | str
    item: str
    currency: str | None = None
    category: str | None = None
    date: str | None = None
    notes: str | None = None


class ExpenseUpdateRequestBody(ApiModel):
    """
    Every field is optional and, when *omitted* entirely, leaves that
    value unchanged - only fields the client actually sends are
    applied (see `handle_update_expense()`). `category`/`notes` may be
    explicitly set to `null`/`""` to clear them.
    """

    amount: float | str | None = None
    currency: str | None = None
    item: str | None = None
    category: str | None = None
    date: str | None = None
    notes: str | None = None


class ExpenseListResponse(ApiModel):
    expenses: tuple[ExpenseBody, ...] = ()
    count: int = 0


class ExpenseMutationResponse(ApiModel):
    expense: ExpenseBody


class ExpenseDeleteResponse(ApiModel):
    removed: ExpenseBody


class ExpenseSummaryResponse(ApiModel):
    period_label: str
    currency: str
    total: str
    count: int
    by_category: dict[str, str] = Field(default_factory=dict)
    by_item: dict[str, str] = Field(default_factory=dict)
    by_date: dict[str, str] = Field(default_factory=dict)
    largest_expenses: tuple[ExpenseBody, ...] = ()


class ExpensePeriodFilterBody(ApiModel):
    """One side of a comparison, or a `list`/`summary` filter."""

    period: str | None = None
    year: int | None = None
    month: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    category: str | None = None


class ExpenseCompareRequestBody(ApiModel):
    period_a: ExpensePeriodFilterBody
    period_b: ExpensePeriodFilterBody
    category: str | None = None


class ExpenseComparisonSideBody(ApiModel):
    label: str
    total: str
    count: int


class ExpenseCompareResponse(ApiModel):
    current: ExpenseComparisonSideBody
    previous: ExpenseComparisonSideBody
    difference: str
    percentage_change: float | None = None
    direction: str
    note: str | None = None
    category_breakdown: dict[str, dict[str, str]] = Field(default_factory=dict)
