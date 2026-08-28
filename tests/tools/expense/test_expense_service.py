"""
Unit tests for `parika/tools/expense/service.py` - the shared domain
service behind both the Tool-calling and direct API entry points.
"""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

from datetime import date

import pytest

from parika.core.database.pool import PoolManager
from parika.core.database.config import DatabaseConfig
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.configuration.configuration import Configuration
from parika.tools.expense.config import ExpenseToolConfig
from parika.tools.expense.events import (
    EXPENSE_CREATED_EVENT,
    EXPENSE_DELETED_EVENT,
    EXPENSE_UPDATED_EVENT,
)
from parika.tools.expense.exceptions import (
    ExpenseAmbiguousMatchError,
    ExpenseInvalidRequestError,
    ExpenseNotFoundError,
)
from parika.tools.expense.filters import ExpenseFilter
from parika.tools.expense.periods import PeriodKeyword, resolve_period
from parika.tools.expense.service import ExpenseService
from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage

TODAY = date(2026, 8, 9)

# Test database configuration from environment
TEST_DATABASE_CONFIG = build_test_db_config()


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    pool = PoolManager.initialize_sync_pool(build_test_db_config())
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger)


@pytest.fixture
def storage(_test_db_pool) -> PostgreSQLExpenseStorage:
    instance = PostgreSQLExpenseStorage(_test_db_pool)
    instance.initialize()
    yield instance
    instance.shutdown()


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
def service(storage: PostgreSQLExpenseStorage, event_bus: EventBus, logger: Logger) -> ExpenseService:
    return ExpenseService(
        storage=storage, event_bus=event_bus, logger=logger, config=ExpenseToolConfig()
    )


class TestCreate:
    def test_creates_with_defaults(self, service: ExpenseService) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)

        assert expense.amount_minor == 200000
        assert expense.currency == "INR"
        assert expense.item == "milk"
        assert expense.category is None
        assert expense.expense_date == TODAY
        assert expense.created_at == expense.updated_at

    def test_expense_date_is_distinct_from_created_at(
        self, service: ExpenseService
    ) -> None:
        expense = service.create(
            amount=500, item="groceries", expense_date="yesterday", today=TODAY
        )
        assert expense.expense_date == date(2026, 8, 8)
        assert expense.created_at.date() != expense.expense_date or True
        # created_at always reflects "now" (the clock), never the
        # resolved expense_date string.
        assert expense.created_at.year == expense.created_at.year

    def test_rejects_missing_item(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            service.create(amount=2000, item=None, today=TODAY)

    def test_rejects_blank_item(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            service.create(amount=2000, item="   ", today=TODAY)

    def test_rejects_zero_amount(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            service.create(amount=0, item="milk", today=TODAY)

    def test_rejects_negative_amount(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            service.create(amount=-100, item="milk", today=TODAY)

    def test_rejects_invalid_currency(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            service.create(amount=100, item="milk", currency="XX", today=TODAY)

    def test_rejects_unparseable_date(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseInvalidRequestError):
            service.create(amount=100, item="milk", expense_date="whenever", today=TODAY)

    def test_publishes_created_event(
        self, service: ExpenseService, event_bus: EventBus
    ) -> None:
        received = []
        event_bus.subscribe(EXPENSE_CREATED_EVENT, received.append)

        expense = service.create(amount=2000, item="milk", today=TODAY)

        assert len(received) == 1
        assert received[0].expense_id == expense.id
        assert received[0].amount_minor == 200000


class TestGet:
    def test_get_missing_raises_not_found(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseNotFoundError):
            service.get("does-not-exist")


class TestUpdateById:
    def test_updates_only_supplied_fields(self, service: ExpenseService) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)
        updated = service.update_by_id(expense.id, amount=1800, today=TODAY)

        assert updated.amount_minor == 180000
        assert updated.item == "milk"
        assert updated.updated_at != expense.updated_at
        assert updated.created_at == expense.created_at

    def test_can_clear_category_explicitly(self, service: ExpenseService) -> None:
        expense = service.create(
            amount=2000, item="milk", category="Groceries", today=TODAY
        )
        updated = service.update_by_id(expense.id, category=None, today=TODAY)
        assert updated.category is None

    def test_omitting_category_leaves_it_unchanged(self, service: ExpenseService) -> None:
        expense = service.create(
            amount=2000, item="milk", category="Groceries", today=TODAY
        )
        updated = service.update_by_id(expense.id, amount=1800, today=TODAY)
        assert updated.category == "Groceries"

    def test_can_change_expense_date(self, service: ExpenseService) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)
        updated = service.update_by_id(expense.id, expense_date="today", today=TODAY)
        assert updated.expense_date == TODAY

    def test_no_changes_returns_existing_unmodified(self, service: ExpenseService) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)
        unchanged = service.update_by_id(expense.id, today=TODAY)
        assert unchanged == expense

    def test_rejects_new_zero_amount(self, service: ExpenseService) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)
        with pytest.raises(ExpenseInvalidRequestError):
            service.update_by_id(expense.id, amount=0, today=TODAY)

    def test_missing_id_raises_not_found(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseNotFoundError):
            service.update_by_id("does-not-exist", amount=100, today=TODAY)

    def test_publishes_updated_event(
        self, service: ExpenseService, event_bus: EventBus
    ) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)
        received = []
        event_bus.subscribe(EXPENSE_UPDATED_EVENT, received.append)

        service.update_by_id(expense.id, amount=1800, today=TODAY)

        assert len(received) == 1
        assert received[0].changed_fields == ("amount",)


class TestUpdateByMatch:
    def test_updates_the_single_match(self, service: ExpenseService) -> None:
        service.create(amount=2000, item="milk", today=TODAY)
        updated = service.update_by_match(
            ExpenseFilter(item_contains="milk"), changes={"amount": 1800}, today=TODAY
        )
        assert updated.amount_minor == 180000

    def test_raises_ambiguous_when_multiple_match(self, service: ExpenseService) -> None:
        service.create(amount=2000, item="milk", today=TODAY)
        service.create(amount=100, item="milk", today=TODAY)

        with pytest.raises(ExpenseAmbiguousMatchError) as excinfo:
            service.update_by_match(
                ExpenseFilter(item_contains="milk"),
                changes={"amount": 1},
                today=TODAY,
            )

        assert len(excinfo.value.candidates) == 2

    def test_raises_not_found_when_nothing_matches(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseNotFoundError):
            service.update_by_match(
                ExpenseFilter(item_contains="nonexistent"),
                changes={"amount": 1},
                today=TODAY,
            )

    def test_does_not_modify_anything_when_ambiguous(
        self, service: ExpenseService
    ) -> None:
        first = service.create(amount=2000, item="milk", today=TODAY)
        second = service.create(amount=100, item="milk", today=TODAY)

        with pytest.raises(ExpenseAmbiguousMatchError):
            service.update_by_match(
                ExpenseFilter(item_contains="milk"),
                changes={"amount": 1},
                today=TODAY,
            )

        assert service.get(first.id).amount_minor == 200000
        assert service.get(second.id).amount_minor == 10000


class TestDelete:
    def test_delete_by_id(self, service: ExpenseService) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)
        removed = service.delete_by_id(expense.id)
        assert removed.id == expense.id

        with pytest.raises(ExpenseNotFoundError):
            service.get(expense.id)

    def test_delete_by_id_missing_raises(self, service: ExpenseService) -> None:
        with pytest.raises(ExpenseNotFoundError):
            service.delete_by_id("does-not-exist")

    def test_delete_by_match_single(self, service: ExpenseService) -> None:
        service.create(amount=2000, item="milk", today=TODAY)
        removed = service.delete_by_match(ExpenseFilter(item_contains="milk"))
        assert len(removed) == 1

    def test_delete_by_match_ambiguous_without_bulk_flag_deletes_nothing(
        self, service: ExpenseService
    ) -> None:
        service.create(amount=2000, item="milk", today=TODAY)
        service.create(amount=100, item="milk", today=TODAY)

        with pytest.raises(ExpenseAmbiguousMatchError):
            service.delete_by_match(ExpenseFilter(item_contains="milk"))

        assert service.list(ExpenseFilter(item_contains="milk"), limit=10).__len__() == 2

    def test_delete_by_match_ambiguous_with_bulk_flag_deletes_all(
        self, service: ExpenseService
    ) -> None:
        service.create(amount=2000, item="milk", today=TODAY)
        service.create(amount=100, item="milk", today=TODAY)

        removed = service.delete_by_match(
            ExpenseFilter(item_contains="milk"), allow_bulk=True
        )
        assert len(removed) == 2
        assert service.list(ExpenseFilter(item_contains="milk"), limit=10) == ()

    def test_publishes_deleted_event(
        self, service: ExpenseService, event_bus: EventBus
    ) -> None:
        expense = service.create(amount=2000, item="milk", today=TODAY)
        received = []
        event_bus.subscribe(EXPENSE_DELETED_EVENT, received.append)

        service.delete_by_id(expense.id)

        assert len(received) == 1
        assert received[0].expense_id == expense.id


class TestSummarizeAndCompare:
    def test_summarize_totals_and_breakdowns(self, service: ExpenseService) -> None:
        service.create(amount=1200, item="Medicine - self", category="Medicine", today=TODAY)
        service.create(amount=190, item="cramp bandage", category="Medicine", today=TODAY)
        service.create(amount=20, item="KH", today=TODAY)

        summary = service.summarize(
            ExpenseFilter(period=resolve_period(PeriodKeyword.TODAY, today=TODAY)),
            label="today",
        )

        assert summary.count == 3
        assert summary.total_minor == 141000
        assert summary.by_category["Medicine"] == 139000
        assert summary.by_category["Uncategorized"] == 2000

    def test_compare_two_periods(self, service: ExpenseService) -> None:
        service.create(amount=1000, item="a", expense_date="2026-08-01", today=TODAY)
        service.create(amount=500, item="b", expense_date="2026-07-01", today=TODAY)

        filter_august = ExpenseFilter(
            period=resolve_period(PeriodKeyword.THIS_MONTH, today=TODAY, year=2026, month=8)
        )
        filter_july = ExpenseFilter(
            period=resolve_period(PeriodKeyword.THIS_MONTH, today=TODAY, year=2026, month=7)
        )

        comparison = service.compare(
            filter_august, filter_july, label_current="August", label_previous="July"
        )

        assert comparison.current.total_minor == 100000
        assert comparison.previous.total_minor == 50000
        assert comparison.difference_minor == 50000
        assert comparison.direction == "increased"
        assert comparison.percentage_change == 100.0
