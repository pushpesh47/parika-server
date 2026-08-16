"""
PARIKA API - Expense Router

Direct, structured CRUD/filter/summary/comparison endpoints for the
Web Client's Expense Management dashboard. Natural-language expense
requests ("add rs 2000 for milk today") are never sent here - they go
through the existing `POST /api/v1/chat` pipeline instead, which
reaches the exact same `ExpenseService` through
`expense.add_expense`'s Tool (see
`parika/api/handlers/expense.py`'s module docstring).

Static paths (`/expenses/summary`, `/expenses/compare`) are registered
before the dynamic `/expenses/{expense_id}` path so FastAPI never
tries to interpret "summary"/"compare" as an id.

Direct Expense API endpoints use an API-owned ExpenseService with
its own SQLite connection - they do NOT go through CoreExecutionOwner.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_expense_service
from ..handlers.expense import (
    handle_create_expense,
    handle_delete_expense,
    handle_get_expense,
    handle_list_expenses,
    handle_summarize_expenses,
    handle_update_expense,
    handle_compare_expenses,
)
from ..requests import (
    ExpenseCompareRequest,
    ExpenseCreateRequest,
    ExpenseDeleteRequest,
    ExpenseGetRequest,
    ExpenseListRequest,
    ExpenseSummarizeRequest,
    ExpenseUpdateRequest,
)
from ..schemas.expense import (
    ExpenseCompareRequestBody,
    ExpenseCompareResponse,
    ExpenseCreateRequestBody,
    ExpenseDeleteResponse,
    ExpenseListResponse,
    ExpenseMutationResponse,
    ExpenseSummaryResponse,
    ExpenseUpdateRequestBody,
)
from parika.tools.expense.service import ExpenseService

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.post("", response_model=ExpenseMutationResponse)
def create_expense(
    body: ExpenseCreateRequestBody,
    auth: AuthContext = RequireAuth,
    service: ExpenseService = Depends(get_expense_service),
) -> ExpenseMutationResponse:
    """Add a new expense (mirrors `expense.add_expense`)."""
    request = ExpenseCreateRequest(
        amount=body.amount,
        item=body.item,
        currency=body.currency,
        category=body.category,
        date=body.date,
        notes=body.notes,
    )
    result = handle_create_expense(service, request)
    return ExpenseMutationResponse.model_validate(result)


@router.get("", response_model=ExpenseListResponse)
def list_expenses(
    period: str | None = None,
    year: int | None = None,
    month: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    item: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int | None = None,
    offset: int = 0,
    auth: AuthContext = RequireAuth,
    service: ExpenseService = Depends(get_expense_service),
) -> ExpenseListResponse:
    """List/filter expenses (mirrors `expense.list_expenses`)."""
    request = ExpenseListRequest(
        period=period,
        year=year,
        month=month,
        start_date=start_date,
        end_date=end_date,
        category=category,
        item=item,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
        offset=offset,
    )
    result = handle_list_expenses(service, request)
    return ExpenseListResponse.model_validate(result)


@router.get("/summary", response_model=ExpenseSummaryResponse)
def summarize_expenses(
    period: str | None = None,
    year: int | None = None,
    month: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    item: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    largest_count: int | None = None,
    auth: AuthContext = RequireAuth,
    service: ExpenseService = Depends(get_expense_service),
) -> ExpenseSummaryResponse:
    """
    Deterministic total/count/breakdown for a filtered set of
    expenses (mirrors `expense.summarize_expenses`); the Web Client's
    dashboard totals (today/this week/this month) and category/
    largest-expense views all use this one endpoint with a different
    `period`.
    """
    request = ExpenseSummarizeRequest(
        period=period,
        year=year,
        month=month,
        start_date=start_date,
        end_date=end_date,
        category=category,
        item=item,
        min_amount=min_amount,
        max_amount=max_amount,
        largest_count=largest_count,
    )
    result = handle_summarize_expenses(service, request)
    return ExpenseSummaryResponse.model_validate(result)


@router.post("/compare", response_model=ExpenseCompareResponse)
def compare_expenses(
    body: ExpenseCompareRequestBody,
    auth: AuthContext = RequireAuth,
    service: ExpenseService = Depends(get_expense_service),
) -> ExpenseCompareResponse:
    """Deterministic period comparison (mirrors `expense.compare_periods`)."""
    request = ExpenseCompareRequest(
        period_a=body.period_a.model_dump(),
        period_b=body.period_b.model_dump(),
        category=body.category,
    )
    result = handle_compare_expenses(service, request)
    return ExpenseCompareResponse.model_validate(result)


@router.get("/{expense_id}", response_model=ExpenseMutationResponse)
def get_expense(
    expense_id: str,
    auth: AuthContext = RequireAuth,
    service: ExpenseService = Depends(get_expense_service),
) -> ExpenseMutationResponse:
    """Retrieve one expense by id (mirrors `expense.get_expense`)."""
    request = ExpenseGetRequest(expense_id=expense_id)
    result = handle_get_expense(service, request)
    return ExpenseMutationResponse.model_validate(result)


@router.patch("/{expense_id}", response_model=ExpenseMutationResponse)
def update_expense(
    expense_id: str,
    body: ExpenseUpdateRequestBody,
    auth: AuthContext = RequireAuth,
    service: ExpenseService = Depends(get_expense_service),
) -> ExpenseMutationResponse:
    """
    Partially update one specific expense (mirrors
    `expense.update_expense`'s by-id path). Only fields present in the
    request body are changed - see `ExpenseUpdateRequestBody`.
    """
    changes = _update_changes(body)
    request = ExpenseUpdateRequest(expense_id=expense_id, changes=changes)
    result = handle_update_expense(service, request)
    return ExpenseMutationResponse.model_validate(result)


@router.delete("/{expense_id}", response_model=ExpenseDeleteResponse)
def delete_expense(
    expense_id: str,
    auth: AuthContext = RequireAuth,
    service: ExpenseService = Depends(get_expense_service),
) -> ExpenseDeleteResponse:
    """Delete one specific expense (mirrors `expense.remove_expense`'s by-id path)."""
    request = ExpenseDeleteRequest(expense_id=expense_id)
    result = handle_delete_expense(service, request)
    return ExpenseDeleteResponse.model_validate(result)


def _update_changes(body: ExpenseUpdateRequestBody) -> dict[str, object]:
    """
    Only the fields the client actually sent (`exclude_unset=True`),
    renaming `date` -> `expense_date` to match
    `ExpenseService.update_by_id()`'s keyword - the wire-format field
    is named `date` for symmetry with `ExpenseCreateRequestBody`.
    """

    raw = body.model_dump(exclude_unset=True)

    if "date" in raw:
        raw["expense_date"] = raw.pop("date")

    return raw
