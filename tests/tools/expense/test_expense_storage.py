"""
Unit tests for `parika/tools/expense/postgresql_storage.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from parika.tools.expense.exceptions import ExpensePersistenceError
from parika.tools.expense.filters import ExpenseFilter
from parika.tools.expense.model import Expense
from parika.tools.expense.periods import Period
from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module
from parika.core.database.config import DatabaseConfig


# Test database configuration
TEST_DATABASE_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 5432,
    "database": "parika_test",
    "username": "postgres",
    "password": "dba",
    "pool_min_size": 2,
    "pool_max_size": 10,
    "connect_timeout": 10.0,
    "statement_timeout": 0.0,
    "application_name": "parika_test",
}


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = DatabaseConfig(**TEST_DATABASE_CONFIG)
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture()
def storage(_test_db_pool) -> PostgreSQLExpenseStorage:
    instance = PostgreSQLExpenseStorage(_test_db_pool)
    instance.initialize()
    # Clean up before each test
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.expense;")
            conn.commit()
    yield instance
    instance.shutdown()


def _expense(
    *,
    id: str,
    amount_minor: int,
    item: str,
    category: str | None = None,
    expense_date: date,
) -> Expense:
    now = datetime.now(UTC)
    return Expense(
        id=id,
        amount_minor=amount_minor,
        currency="INR",
        item=item,
        category=category,
        expense_date=expense_date,
        notes=None,
        created_at=now,
        updated_at=now,
    )


def _expense_with_updates(
    base: Expense,
    *,
    amount_minor: int | None = None,
    item: str | None = None,
) -> Expense:
    """Create a new Expense with updated fields (since Expense is frozen)."""
    from dataclasses import replace
    return replace(
        base,
        amount_minor=amount_minor if amount_minor is not None else base.amount_minor,
        item=item if item is not None else base.item,
    )


class TestExpenseStorage:
    def test_initialize_creates_schema(self, storage: PostgreSQLExpenseStorage) -> None:
        # Should not raise
        assert storage._pool is not None

    def test_insert_and_get(self, storage: PostgreSQLExpenseStorage) -> None:
        expense = _expense(
            id="exp1",
            amount_minor=10000,
            item="coffee",
            expense_date=date(2024, 1, 15),
        )
        inserted = storage.insert(expense)
        assert inserted == expense

        retrieved = storage.get("exp1")
        assert retrieved is not None
        assert retrieved.id == "exp1"
        assert retrieved.amount_minor == 10000
        assert retrieved.item == "coffee"
        assert retrieved.expense_date == date(2024, 1, 15)

    def test_get_nonexistent_returns_none(self, storage: PostgreSQLExpenseStorage) -> None:
        assert storage.get("nonexistent") is None

    def test_update(self, storage: PostgreSQLExpenseStorage) -> None:
        expense = _expense(
            id="exp1",
            amount_minor=10000,
            item="coffee",
            expense_date=date(2024, 1, 15),
        )
        storage.insert(expense)

        updated = storage.update(
            _expense_with_updates(expense, amount_minor=15000, item="latte")
        )
        assert updated is not None
        assert updated.amount_minor == 15000
        assert updated.item == "latte"

        retrieved = storage.get("exp1")
        assert retrieved is not None
        assert retrieved.amount_minor == 15000
        assert retrieved.item == "latte"

    def test_update_nonexistent_raises(self, storage: PostgreSQLExpenseStorage) -> None:
        expense = _expense(
            id="exp1",
            amount_minor=10000,
            item="coffee",
            expense_date=date(2024, 1, 15),
        )
        with pytest.raises(ExpensePersistenceError, match="Cannot update unknown expense"):
            storage.update(expense)

    def test_delete(self, storage: PostgreSQLExpenseStorage) -> None:
        expense = _expense(
            id="exp1",
            amount_minor=10000,
            item="coffee",
            expense_date=date(2024, 1, 15),
        )
        storage.insert(expense)

        deleted = storage.delete("exp1")
        assert deleted is not None
        assert deleted.id == "exp1"

        assert storage.get("exp1") is None

    def test_delete_nonexistent_returns_none(self, storage: PostgreSQLExpenseStorage) -> None:
        result = storage.delete("nonexistent")
        assert result is None

    def test_find_without_filter(self, storage: PostgreSQLExpenseStorage) -> None:
        e1 = _expense(id="e1", amount_minor=100, item="a", expense_date=date(2024, 1, 1))
        e2 = _expense(id="e2", amount_minor=200, item="b", expense_date=date(2024, 1, 2))
        storage.insert(e1)
        storage.insert(e2)

        results = storage.find(ExpenseFilter(), limit=10)
        assert len(results) == 2

    def test_find_with_date_filter(self, storage: PostgreSQLExpenseStorage) -> None:
        e1 = _expense(id="e1", amount_minor=100, item="a", expense_date=date(2024, 1, 1))
        e2 = _expense(id="e2", amount_minor=200, item="b", expense_date=date(2024, 1, 2))
        storage.insert(e1)
        storage.insert(e2)

        filter_obj = ExpenseFilter(period=Period(start=date(2024, 1, 1), end=date(2024, 1, 1), label="2024-01-01"))
        results = storage.find(filter_obj, limit=10)
        assert len(results) == 1
        assert results[0].id == "e1"

    def test_find_with_category_filter(self, storage: PostgreSQLExpenseStorage) -> None:
        e1 = _expense(id="e1", amount_minor=100, item="a", category="Food", expense_date=date(2024, 1, 1))
        e2 = _expense(id="e2", amount_minor=200, item="b", category="Transport", expense_date=date(2024, 1, 2))
        storage.insert(e1)
        storage.insert(e2)

        filter_obj = ExpenseFilter(category="Food")
        results = storage.find(filter_obj, limit=10)
        assert len(results) == 1
        assert results[0].category == "Food"

    def test_count(self, storage: PostgreSQLExpenseStorage) -> None:
        assert storage.count(ExpenseFilter()) == 0
        storage.insert(_expense(id="e1", amount_minor=100, item="a", expense_date=date(2024, 1, 1)))
        assert storage.count(ExpenseFilter()) == 1

    def test_sum_amount_minor(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="a", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="b", expense_date=date(2024, 1, 2)))

        assert storage.sum_amount_minor(ExpenseFilter()) == 300

    def test_aggregate_by_category(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="a", category="Food", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="b", category="Food", expense_date=date(2024, 1, 2)))
        storage.insert(_expense(id="e3", amount_minor=300, item="c", category="Transport", expense_date=date(2024, 1, 3)))

        agg = storage.aggregate_by_category(ExpenseFilter())
        assert agg.get("Food") == 300
        assert agg.get("Transport") == 300

    def test_aggregate_by_item(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="coffee", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="coffee", expense_date=date(2024, 1, 2)))

        agg = storage.aggregate_by_item(ExpenseFilter())
        assert agg.get("coffee") == 300

    def test_aggregate_by_date(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="a", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="b", expense_date=date(2024, 1, 2)))

        agg = storage.aggregate_by_date(ExpenseFilter())
        assert agg.get("2024-01-01") == 100
        assert agg.get("2024-01-02") == 200

    def test_aggregate_by_month(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="a", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="b", expense_date=date(2024, 1, 15)))

        agg = storage.aggregate_by_month(ExpenseFilter())
        assert agg.get("2024-01") == 300

    def test_largest(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="a", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=300, item="b", expense_date=date(2024, 1, 2)))
        storage.insert(_expense(id="e3", amount_minor=200, item="c", expense_date=date(2024, 1, 3)))

        largest = storage.largest(ExpenseFilter(), limit=2)
        assert len(largest) == 2
        assert largest[0].amount_minor == 300
        assert largest[1].amount_minor == 200

    def test_update_by_id(self, storage: PostgreSQLExpenseStorage) -> None:
        expense = _expense(
            id="exp1",
            amount_minor=10000,
            item="coffee",
            expense_date=date(2024, 1, 15),
        )
        storage.insert(expense)

        updated = storage.update_by_id("exp1", updates={"amount_minor": 15000, "item": "latte"})
        assert updated.amount_minor == 15000
        assert updated.item == "latte"

    def test_update_by_id_nonexistent_raises(self, storage: PostgreSQLExpenseStorage) -> None:
        with pytest.raises(ExpensePersistenceError, match="unknown expense"):
            storage.update_by_id("nonexistent", updates={"amount_minor": 100})

    def test_delete_by_id(self, storage: PostgreSQLExpenseStorage) -> None:
        expense = _expense(id="exp1", amount_minor=10000, item="coffee", expense_date=date(2024, 1, 15))
        storage.insert(expense)

        deleted = storage.delete_by_id("exp1")
        assert deleted is not None
        assert deleted.id == "exp1"
        assert storage.get("exp1") is None

    def test_delete_by_id_nonexistent_returns_none(self, storage: PostgreSQLExpenseStorage) -> None:
        result = storage.delete_by_id("nonexistent")
        assert result is None

    def test_update_by_match(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="coffee", category="Food", expense_date=date(2024, 1, 1)))

        updated = storage.update_by_match(
            ExpenseFilter(category="Food"),
            updates={"amount_minor": 200}
        )
        assert updated.amount_minor == 200

    def test_update_by_match_nonexistent_raises(self, storage: PostgreSQLExpenseStorage) -> None:
        with pytest.raises(ExpensePersistenceError, match="No expense matched"):
            storage.update_by_match(ExpenseFilter(category="Nonexistent"), updates={})

    def test_update_by_match_ambiguous_raises(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="coffee", category="Food", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="tea", category="Food", expense_date=date(2024, 1, 2)))

        with pytest.raises(ExpensePersistenceError, match="match this description"):
            storage.update_by_match(ExpenseFilter(category="Food"), updates={})

    def test_delete_by_match(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="coffee", category="Food", expense_date=date(2024, 1, 1)))

        deleted = storage.delete_by_match(ExpenseFilter(category="Food"), allow_bulk=True)
        assert len(deleted) == 1
        assert deleted[0].id == "e1"

    def test_delete_by_match_nonexistent_raises(self, storage: PostgreSQLExpenseStorage) -> None:
        with pytest.raises(ExpensePersistenceError, match="No expense matched"):
            storage.delete_by_match(ExpenseFilter(category="Nonexistent"), allow_bulk=True)

    def test_delete_by_match_ambiguous_without_bulk_raises(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="coffee", category="Food", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="tea", category="Food", expense_date=date(2024, 1, 2)))

        with pytest.raises(ExpensePersistenceError, match="match this description"):
            storage.delete_by_match(ExpenseFilter(category="Food"), allow_bulk=False)

    def test_delete_by_match_bulk(self, storage: PostgreSQLExpenseStorage) -> None:
        storage.insert(_expense(id="e1", amount_minor=100, item="coffee", category="Food", expense_date=date(2024, 1, 1)))
        storage.insert(_expense(id="e2", amount_minor=200, item="tea", category="Food", expense_date=date(2024, 1, 2)))

        deleted = storage.delete_by_match(ExpenseFilter(category="Food"), allow_bulk=True)
        assert len(deleted) == 2

    def test_empty_result_behavior(self, storage: PostgreSQLExpenseStorage) -> None:
        filter_obj = ExpenseFilter(period=Period(start=date(2024, 1, 1), end=date(2024, 1, 31), label="2024-01"))
        assert storage.find(filter_obj, limit=10) == ()
        assert storage.count(filter_obj) == 0
        assert storage.sum_amount_minor(filter_obj) == 0
        assert storage.aggregate_by_category(filter_obj) == {}
        assert storage.aggregate_by_item(filter_obj) == {}
        assert storage.aggregate_by_date(filter_obj) == {}
        assert storage.aggregate_by_month(filter_obj) == {}
        assert storage.largest(filter_obj, limit=5) == ()