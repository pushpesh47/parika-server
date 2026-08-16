"""
PARIKA API - Expense Handler

Translates the direct, structured `/api/v1/expenses...` requests (the
Web Client's CRUD/dashboard surface: "add expense", "edit expense",
"delete expense", filters, summaries, comparisons) into calls against
the *same*, single `ExpenseService` instance the natural-language
Tool-calling path (`parika/tools/expense/driver.py`) already uses -
reached here directly through `ServiceContainer`, exactly like
`TtsOperationRegistry`/`VoiceLanguagePreferenceStore` are for the
Voice API (`parika/api/handlers/voice.py`).

This is a deliberate, *direct* service call rather than going through
`ToolManager.execute()`: `ToolManager` uniformly wraps every
exception into a generic `ToolExecutionError` (see
`parika/core/tool_manager/tool_manager.py`), which would collapse
`ExpenseNotFoundError`/`ExpenseInvalidRequestError`/
`ExpenseAmbiguousMatchError` into an indistinguishable HTTP 500 for
every structured API caller. Calling `ExpenseService` directly lets
the original exception type reach `parika/api/errors.py`'s existing
suffix-matching table (`NotFoundError` -> 404, `InvalidRequestError`
-> 400, and the one additive `AmbiguousMatchError` -> 409 entry it
adds - see that module's own docstring) with zero per-endpoint
try/except here.

Never constructs a `Goal`/`BrainRequest` and never calls
`Brain`/`Planner` - see `parika/api/handlers/__init__.py`'s
orchestration/translation-only rule every handler in this package
follows. Match-based (no explicit id) update/delete is intentionally
*not* exposed on this direct API surface: the Web Client always knows
a specific `expense_id` (it lists expenses, with their ids, before
ever editing/deleting one) - match-based resolution is a
natural-language-only concern, handled exclusively by
`ExpenseToolDriver`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from parika.tools.expense.driver import build_expense_filter
from parika.tools.expense.exceptions import ExpenseInvalidRequestError
from parika.tools.expense.filters import ExpenseFilter
from parika.tools.expense.money import from_minor_units
from parika.tools.expense.service import ExpenseService

from ..requests import (
    ExpenseCompareRequest,
    ExpenseCreateRequest,
    ExpenseDeleteRequest,
    ExpenseGetRequest,
    ExpenseListRequest,
    ExpenseSummarizeRequest,
    ExpenseUpdateRequest,
)


def handle_create_expense(
    service: ExpenseService, request: ExpenseCreateRequest
) -> dict[str, Any]:
    expense = service.create(
        amount=request.amount,
        item=request.item,
        currency=request.currency,
        category=request.category,
        expense_date=request.date,
        notes=request.notes,
        today=date.today(),
    )
    return {"expense": expense.to_dict()}


def handle_get_expense(
    service: ExpenseService, request: ExpenseGetRequest
) -> dict[str, Any]:
    expense = service.get(request.expense_id)
    return {"expense": expense.to_dict()}


def handle_list_expenses(
    service: ExpenseService, request: ExpenseListRequest
) -> dict[str, Any]:
    today = date.today()
    expense_filter = build_expense_filter(_filter_arguments(request), today=today)

    expenses = service.list(
        expense_filter, limit=request.limit, offset=request.offset
    )

    return {
        "expenses": [expense.to_dict() for expense in expenses],
        "count": len(expenses),
    }


def handle_update_expense(
    service: ExpenseService, request: ExpenseUpdateRequest
) -> dict[str, Any]:
    updated = service.update_by_id(
        request.expense_id, today=date.today(), **dict(request.changes)
    )
    return {"expense": updated.to_dict()}


def handle_delete_expense(
    service: ExpenseService, request: ExpenseDeleteRequest
) -> dict[str, Any]:
    removed = service.delete_by_id(request.expense_id)
    return {"removed": removed.to_dict()}


def handle_summarize_expenses(
    service: ExpenseService, request: ExpenseSummarizeRequest
) -> dict[str, Any]:
    today = date.today()
    expense_filter = build_expense_filter(_filter_arguments(request), today=today)
    label = expense_filter.period.label if expense_filter.period is not None else "all time"

    summary = service.summarize(
        expense_filter, label=label, largest_count=request.largest_count
    )

    return {
        "period_label": summary.period_label,
        "currency": summary.currency,
        "total": _amount(summary.total_minor),
        "count": summary.count,
        "by_category": {k: _amount(v) for k, v in summary.by_category.items()},
        "by_item": {k: _amount(v) for k, v in summary.by_item.items()},
        "by_date": {k: _amount(v) for k, v in summary.by_date.items()},
        "largest_expenses": [expense.to_dict() for expense in summary.largest],
    }


def handle_compare_expenses(
    service: ExpenseService, request: ExpenseCompareRequest
) -> dict[str, Any]:
    today = date.today()
    filter_a = build_expense_filter(dict(request.period_a), today=today)
    filter_b = build_expense_filter(dict(request.period_b), today=today)

    if request.category:
        filter_a = _with_category(filter_a, request.category)
        filter_b = _with_category(filter_b, request.category)

    if filter_a.period is None or filter_b.period is None:
        raise ExpenseInvalidRequestError(
            "period_a and period_b each require a period (or "
            "start_date/end_date)."
        )

    comparison = service.compare(
        filter_a,
        filter_b,
        label_current=filter_a.period.label,
        label_previous=filter_b.period.label,
    )

    return {
        "current": {
            "label": comparison.current.label,
            "total": _amount(comparison.current.total_minor),
            "count": comparison.current.count,
        },
        "previous": {
            "label": comparison.previous.label,
            "total": _amount(comparison.previous.total_minor),
            "count": comparison.previous.count,
        },
        "difference": _amount(comparison.difference_minor),
        "percentage_change": comparison.percentage_change,
        "direction": comparison.direction,
        "note": comparison.note,
        "category_breakdown": {
            category: {
                "current": _amount(current_minor),
                "previous": _amount(previous_minor),
                "difference": _amount(difference_minor),
            }
            for category, (
                current_minor,
                previous_minor,
                difference_minor,
            ) in comparison.category_breakdown.items()
        },
    }


def _filter_arguments(request: Any) -> dict[str, Any]:
    return {
        "period": request.period,
        "year": request.year,
        "month": request.month,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "category": request.category,
        "item": getattr(request, "item", None),
        "min_amount": request.min_amount,
        "max_amount": request.max_amount,
    }


def _with_category(expense_filter: ExpenseFilter, category: str) -> ExpenseFilter:
    return replace(expense_filter, category=category)


def _amount(minor_units: int) -> str:
    return str(from_minor_units(minor_units))
