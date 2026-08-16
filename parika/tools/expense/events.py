"""
PARIKA Expense Tool - Domain Events

Expense Management publishes three domain events for meaningful
mutations, following `<component>.<action>` naming exactly like
`tool.registered`/`module.loaded` elsewhere in Core. Every event is
published through the existing `EventBus` (see `service.py`) - no new
event infrastructure is introduced.

Payload contracts:

    expense.created  -> ExpenseCreated
    expense.updated  -> ExpenseUpdated
    expense.deleted  -> ExpenseDeleted

These are useful (e.g. a future budgeting/notification module could
subscribe to `expense.created` without coupling to Expense
Management's internals) but Expense Management itself never
subscribes to its own events - see
`docs/architecture/adr/0003-expense-management.md`, Decision 6.
"""

from __future__ import annotations

from dataclasses import dataclass

EXPENSE_CREATED_EVENT = "expense.created"
EXPENSE_UPDATED_EVENT = "expense.updated"
EXPENSE_DELETED_EVENT = "expense.deleted"


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseCreated:
    """Payload for `expense.created`."""

    expense_id: str
    amount_minor: int
    currency: str
    item: str
    category: str | None
    expense_date: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseUpdated:
    """Payload for `expense.updated`."""

    expense_id: str
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseDeleted:
    """Payload for `expense.deleted`."""

    expense_id: str
