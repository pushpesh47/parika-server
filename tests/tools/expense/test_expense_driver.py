"""
Unit tests for `parika/tools/expense/driver.py` (`ExpenseToolDriver`),
including the ambiguous-match/not-found safety behavior.
"""

from __future__ import annotations

from datetime import date

import pytest

from parika.core.configuration.configuration import Configuration
from parika.core.database.pool import PoolManager
from parika.core.database.config import DatabaseConfig
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.tool_manager.request import ToolRequest
from parika.tools.expense.config import ExpenseToolConfig
from parika.tools.expense.driver import ExpenseToolDriver
from parika.tools.expense.exceptions import ExpenseInvalidRequestError
from parika.tools.expense.manifest import ExpenseOperation
from parika.tools.expense.service import ExpenseService
from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage

TODAY = date(2026, 8, 9)

TEST_DATABASE_CONFIG = DatabaseConfig(
    enabled=True,
    host="127.0.0.1",
    port=5432,
    database="parika_test",
    username="postgres",
    password="dba",
    pool_min_size=1,
    pool_max_size=10,
    connect_timeout=10.0,
    statement_timeout=0.0,
    application_name="parika_test",
    sslmode="disable",
)


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    pool = PoolManager.initialize_sync_pool(TEST_DATABASE_CONFIG)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture(autouse=True)
def _clear_expense_db(_test_db_pool):
    """Clear the expense database before each test to ensure isolation."""
    storage = PostgreSQLExpenseStorage(_test_db_pool)
    storage.initialize()
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.expense;")
            conn.commit()
    storage.shutdown()
    yield


@pytest.fixture
def service(_test_db_pool) -> ExpenseService:
    logger = Logger(Configuration())
    event_bus = EventBus(logger)
    storage = PostgreSQLExpenseStorage(_test_db_pool)
    storage.initialize()
    return ExpenseService(
        storage=storage, event_bus=event_bus, logger=logger, config=ExpenseToolConfig()
    )


def _driver(operation: ExpenseOperation, service: ExpenseService) -> ExpenseToolDriver:
    return ExpenseToolDriver(operation, service=service)


class TestAdd:
    def test_add_expense_success(self, service: ExpenseService) -> None:
        driver = _driver(ExpenseOperation.ADD, service)
        response = driver.execute(
            ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"})
        )
        assert response.result["status"] == "success"
        assert response.result["expense"]["amount"] == "2000.00"
        assert response.result["expense"]["item"] == "milk"

    def test_add_expense_missing_item_raises(self, service: ExpenseService) -> None:
        driver = _driver(ExpenseOperation.ADD, service)
        with pytest.raises(ExpenseInvalidRequestError):
            driver.execute(ToolRequest(arguments={"amount": 2000}))


class TestListAndSummarizeAndCompare:
    def test_list_filters_by_period(self, service: ExpenseService) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        add.execute(ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"}))
        add.execute(
            ToolRequest(arguments={"amount": 500, "item": "groceries", "date": "5 August 2025"})
        )

        list_driver = _driver(ExpenseOperation.LIST, service)
        response = list_driver.execute(ToolRequest(arguments={"period": "today"}))

        assert response.result["count"] == 1
        assert response.result["expenses"][0]["item"] == "milk"

    def test_summarize_returns_deterministic_total(self, service: ExpenseService) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        add.execute(ToolRequest(arguments={"amount": 1200, "item": "medicine", "date": "today"}))
        add.execute(ToolRequest(arguments={"amount": 190, "item": "bandage", "date": "today"}))

        summarize = _driver(ExpenseOperation.SUMMARIZE, service)
        response = summarize.execute(ToolRequest(arguments={"period": "today"}))

        assert response.result["total"] == "1390.00"
        assert response.result["count"] == 2

    def test_compare_periods(self, service: ExpenseService) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        add.execute(ToolRequest(arguments={"amount": 1000, "item": "a", "date": "2026-08-01"}))
        add.execute(ToolRequest(arguments={"amount": 500, "item": "b", "date": "2026-07-01"}))

        compare = _driver(ExpenseOperation.COMPARE, service)
        response = compare.execute(
            ToolRequest(
                arguments={
                    "period_a": {"period": "this_month", "year": 2026, "month": 8},
                    "period_b": {"period": "this_month", "year": 2026, "month": 7},
                }
            )
        )

        assert response.result["current"]["total"] == "1000.00"
        assert response.result["previous"]["total"] == "500.00"
        assert response.result["direction"] == "increased"
        assert response.result["percentage_change"] == 100.0

    def test_compare_requires_a_period_on_both_sides(self, service: ExpenseService) -> None:
        compare = _driver(ExpenseOperation.COMPARE, service)
        with pytest.raises(ExpenseInvalidRequestError):
            compare.execute(ToolRequest(arguments={"period_a": {}, "period_b": {}}))


class TestUpdateAmbiguitySafety:
    def test_update_by_id_when_known(self, service: ExpenseService) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        created = add.execute(
            ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"})
        ).result["expense"]

        update = _driver(ExpenseOperation.UPDATE, service)
        response = update.execute(
            ToolRequest(arguments={"expense_id": created["id"], "amount": 1800})
        )
        assert response.result["status"] == "success"
        assert response.result["expense"]["amount"] == "1800.00"

    def test_update_by_match_single_candidate(self, service: ExpenseService) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        add.execute(ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"}))

        update = _driver(ExpenseOperation.UPDATE, service)
        response = update.execute(
            ToolRequest(arguments={"item": "milk", "amount": 1800})
        )
        assert response.result["status"] == "success"

    def test_update_by_match_ambiguous_does_not_modify_anything(
        self, service: ExpenseService
    ) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        add.execute(ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"}))
        add.execute(ToolRequest(arguments={"amount": 100, "item": "milk", "date": "today"}))

        update = _driver(ExpenseOperation.UPDATE, service)
        response = update.execute(ToolRequest(arguments={"item": "milk", "amount": 1}))

        assert response.result["status"] == "ambiguous"
        assert len(response.result["candidates"]) == 2

        list_driver = _driver(ExpenseOperation.LIST, service)
        listed = list_driver.execute(ToolRequest(arguments={"item": "milk"})).result
        amounts = {e["amount"] for e in listed["expenses"]}
        assert amounts == {"2000.00", "100.00"}

    def test_update_by_match_not_found(self, service: ExpenseService) -> None:
        update = _driver(ExpenseOperation.UPDATE, service)
        response = update.execute(
            ToolRequest(arguments={"item": "nonexistent", "amount": 1})
        )
        assert response.result["status"] == "not_found"


class TestRemoveAmbiguitySafety:
    def test_remove_by_match_ambiguous_deletes_nothing(self, service: ExpenseService) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        add.execute(ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"}))
        add.execute(ToolRequest(arguments={"amount": 100, "item": "milk", "date": "today"}))

        remove = _driver(ExpenseOperation.REMOVE, service)
        response = remove.execute(ToolRequest(arguments={"item": "milk"}))

        assert response.result["status"] == "ambiguous"

        list_driver = _driver(ExpenseOperation.LIST, service)
        listed = list_driver.execute(ToolRequest(arguments={"item": "milk"})).result
        assert listed["count"] == 2

    def test_remove_by_match_with_explicit_bulk_confirmation_deletes_all(
        self, service: ExpenseService
    ) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        add.execute(ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"}))
        add.execute(ToolRequest(arguments={"amount": 100, "item": "milk", "date": "today"}))

        remove = _driver(ExpenseOperation.REMOVE, service)
        response = remove.execute(
            ToolRequest(arguments={"item": "milk", "confirm_bulk_delete": True})
        )

        assert response.result["status"] == "success"
        assert len(response.result["removed"]) == 2

    def test_remove_by_id(self, service: ExpenseService) -> None:
        add = _driver(ExpenseOperation.ADD, service)
        created = add.execute(
            ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"})
        ).result["expense"]

        remove = _driver(ExpenseOperation.REMOVE, service)
        response = remove.execute(ToolRequest(arguments={"expense_id": created["id"]}))
        assert response.result["status"] == "success"
        assert response.result["removed"][0]["id"] == created["id"]
