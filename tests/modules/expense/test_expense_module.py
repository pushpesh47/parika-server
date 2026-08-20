"""
Unit tests for the Expense Management Module's lifecycle.
"""

from __future__ import annotations

import pytest

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.database.pool import PoolManager
from parika.core.database.config import DatabaseConfig
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.module_manager.state import ModuleState
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.expense.driver import MODULE_HEALTH_COMPONENT_ID, ExpenseModuleDriver
from parika.modules.expense.manifest import EXPENSE_MODULE_ID, create_expense_module
from parika.tools.expense.config import ExpenseToolConfig
from parika.tools.expense.manifest import (
    EXPENSE_CAPABILITY_ADD,
    EXPENSE_CAPABILITY_COMPARE,
    EXPENSE_TOOL_ID_ADD,
    ExpenseOperation,
    OPERATION_CAPABILITY_ID,
    OPERATION_TOOL_ID,
)
from parika.tools.expense.service import ExpenseService
from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage


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


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger=logger)


@pytest.fixture
def capability_registry(event_bus: EventBus, logger: Logger) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def health_manager(event_bus: EventBus, logger: Logger) -> HealthManager:
    return HealthManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def module_manager(event_bus: EventBus, logger: Logger) -> ModuleManager:
    return ModuleManager(configuration=Configuration(), event_bus=event_bus, logger=logger)


@pytest.fixture
def service(_test_db_pool, event_bus: EventBus, logger: Logger) -> ExpenseService:
    storage = PostgreSQLExpenseStorage(_test_db_pool)
    storage.initialize()
    return ExpenseService(
        storage=storage, event_bus=event_bus, logger=logger, config=ExpenseToolConfig()
    )


class TestModuleLifecycle:
    def test_load_registers_every_capability_and_tool(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        service: ExpenseService,
        logger: Logger,
    ) -> None:
        driver = ExpenseModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            service=service,
            logger=logger,
            health_manager=health_manager,
        )
        module_manager.register(create_expense_module(driver))
        module_manager.load(EXPENSE_MODULE_ID)

        for operation in ExpenseOperation:
            assert capability_registry.contains(OPERATION_CAPABILITY_ID[operation])
            assert tool_manager.contains(OPERATION_TOOL_ID[operation])

        assert module_manager.get(EXPENSE_MODULE_ID).state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        service: ExpenseService,
        logger: Logger,
    ) -> None:
        driver = ExpenseModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            service=service,
            logger=logger,
            health_manager=health_manager,
        )
        module_manager.register(create_expense_module(driver))
        module_manager.load(EXPENSE_MODULE_ID)

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
        assert health_manager.run_check(MODULE_HEALTH_COMPONENT_ID).status is HealthStatus.HEALTHY

    def test_unload_unregisters_everything(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        service: ExpenseService,
        logger: Logger,
    ) -> None:
        driver = ExpenseModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            service=service,
            logger=logger,
        )
        module_manager.register(create_expense_module(driver))
        module_manager.load(EXPENSE_MODULE_ID)
        module_manager.unload(EXPENSE_MODULE_ID)

        assert not capability_registry.contains(EXPENSE_CAPABILITY_ADD)
        assert not capability_registry.contains(EXPENSE_CAPABILITY_COMPARE)

    def test_disabled_by_configuration_never_registers(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        logger: Logger,
        _test_db_pool,
    ) -> None:
        storage = PostgreSQLExpenseStorage(_test_db_pool)
        storage.initialize()
        disabled_service = ExpenseService(
            storage=storage,
            event_bus=event_bus,
            logger=logger,
            config=ExpenseToolConfig(enabled=False),
        )

        driver = ExpenseModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            service=disabled_service,
            logger=logger,
        )
        module_manager.register(create_expense_module(driver))
        module_manager.load(EXPENSE_MODULE_ID)

        assert not capability_registry.contains(EXPENSE_CAPABILITY_ADD)


class TestToolExecutionThroughModule:
    def test_add_expense_executes_through_tool_manager(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        service: ExpenseService,
        logger: Logger,
    ) -> None:
        driver = ExpenseModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            service=service,
            logger=logger,
        )
        module_manager.register(create_expense_module(driver))
        module_manager.load(EXPENSE_MODULE_ID)

        response = tool_manager.execute(
            EXPENSE_TOOL_ID_ADD,
            ToolRequest(arguments={"amount": 2000, "item": "milk", "date": "today"}),
        )

        assert response.result["status"] == "success"
        assert response.result["expense"]["item"] == "milk"
