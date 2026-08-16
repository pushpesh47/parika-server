"""
Tests for the direct, structured `/api/v1/expenses...` endpoints.
"""

from __future__ import annotations


def test_create_and_get_expense(client) -> None:
    response = client.post(
        "/api/v1/expenses",
        json={"amount": 2000, "item": "milk", "date": "today"},
    )
    assert response.status_code == 200
    body = response.json()
    expense_id = body["expense"]["id"]
    assert body["expense"]["amount"] == "2000.00"
    assert body["expense"]["currency"] == "INR"

    get_response = client.get(f"/api/v1/expenses/{expense_id}")
    assert get_response.status_code == 200
    assert get_response.json()["expense"]["item"] == "milk"


def test_create_rejects_missing_item(client) -> None:
    response = client.post("/api/v1/expenses", json={"amount": 100})
    assert response.status_code == 422


def test_create_rejects_non_positive_amount(client) -> None:
    response = client.post("/api/v1/expenses", json={"amount": 0, "item": "bad"})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "ExpenseInvalidRequestError"


def test_get_unknown_expense_returns_404(client) -> None:
    response = client.get("/api/v1/expenses/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "ExpenseNotFoundError"


def test_list_filters_by_period(client) -> None:
    client.post(
        "/api/v1/expenses",
        json={"amount": 2000, "item": "unique-router-test-item", "date": "today"},
    )

    response = client.get(
        "/api/v1/expenses", params={"period": "today", "item": "unique-router-test-item"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["expenses"][0]["item"] == "unique-router-test-item"


def test_update_only_changes_supplied_fields(client) -> None:
    created = client.post(
        "/api/v1/expenses",
        json={"amount": 2000, "item": "update-router-test", "category": "Groceries"},
    ).json()["expense"]

    updated = client.patch(
        f"/api/v1/expenses/{created['id']}", json={"amount": 1800}
    )
    assert updated.status_code == 200
    body = updated.json()["expense"]
    assert body["amount"] == "1800.00"
    assert body["category"] == "Groceries"


def test_update_can_clear_category(client) -> None:
    created = client.post(
        "/api/v1/expenses",
        json={"amount": 2000, "item": "clear-category-test", "category": "Groceries"},
    ).json()["expense"]

    updated = client.patch(f"/api/v1/expenses/{created['id']}", json={"category": None})
    assert updated.status_code == 200
    assert updated.json()["expense"]["category"] is None


def test_delete_expense(client) -> None:
    created = client.post(
        "/api/v1/expenses", json={"amount": 500, "item": "delete-router-test"}
    ).json()["expense"]

    deleted = client.delete(f"/api/v1/expenses/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["removed"]["id"] == created["id"]

    missing = client.get(f"/api/v1/expenses/{created['id']}")
    assert missing.status_code == 404


def test_summary_returns_deterministic_total(client) -> None:
    client.post(
        "/api/v1/expenses",
        json={"amount": 1200, "item": "summary-router-medicine", "category": "Medicine", "date": "today"},
    )
    client.post(
        "/api/v1/expenses",
        json={"amount": 190, "item": "summary-router-bandage", "category": "Medicine", "date": "today"},
    )

    response = client.get(
        "/api/v1/expenses/summary", params={"period": "today", "item": "summary-router"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == "1390.00"
    assert body["count"] == 2


def test_compare_periods(client) -> None:
    client.post(
        "/api/v1/expenses",
        json={"amount": 1000, "item": "compare-router-a", "date": "2026-08-01"},
    )
    client.post(
        "/api/v1/expenses",
        json={"amount": 500, "item": "compare-router-a", "date": "2026-07-01"},
    )

    response = client.post(
        "/api/v1/expenses/compare",
        json={
            "period_a": {"period": "this_month", "year": 2026, "month": 8},
            "period_b": {"period": "this_month", "year": 2026, "month": 7},
            "category": None,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["direction"] in ("increased", "decreased", "unchanged")
    assert "percentage_change" in body


def test_compare_handles_zero_comparison_period(client) -> None:
    client.post(
        "/api/v1/expenses",
        json={"amount": 700, "item": "zero-compare-router-test", "date": "2026-08-02"},
    )

    response = client.post(
        "/api/v1/expenses/compare",
        json={
            "period_a": {"start_date": "2026-08-02", "end_date": "2026-08-02", "period": "custom"},
            "period_b": {"start_date": "1999-01-01", "end_date": "1999-01-02", "period": "custom"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["percentage_change"] is None
    assert body["note"] is not None
