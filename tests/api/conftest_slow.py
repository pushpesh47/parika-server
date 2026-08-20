"""
PARIKA Test - Conftest with Slow Module

Extended test configuration that includes the test_slow module for
concurrency testing.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from parika.interfaces.runtime import ParikaRuntime, build_default_runtime
from parika.server.app import create_app
from parika.tools.test_slow import create_test_slow_module
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module
from parika.core.database.config import DatabaseConfig


# Test database configuration - uses a test database
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


@pytest.fixture(scope="session", autouse=True)
def _setup_test_database():
    """Set up test database configuration for all tests."""
    original_load = db_config_module.load_database_config
    
    def patched_load(configuration):
        return DatabaseConfig(**TEST_DATABASE_CONFIG)
    
    db_config_module.load_database_config = patched_load
    yield
    db_config_module.load_database_config = original_load


@pytest.fixture(scope="session")
def _test_db_pool(_setup_test_database):
    """Initialize PostgreSQL test pool for the test session."""
    db_config = DatabaseConfig(**TEST_DATABASE_CONFIG)
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture(scope="module")
def runtime_factory_with_slow_module(_test_db_pool, tmp_path_factory):
    """
    Runtime factory that includes the test_slow module.
    
    This allows tests to create deterministic long-running Core operations
    by calling the test.slow_operation capability.
    """
    data_directory = tmp_path_factory.mktemp("parika-api-data")

    def _factory() -> ParikaRuntime:
        runtime = build_default_runtime(
            discover_ollama_models=False,
            discover_comfyui_models=False,
            discover_local_speech_models=False,
            load_modules=True,
            data_directory=data_directory,
            sync_pool=_test_db_pool,
        )
        
        # Register and load the test slow module
        test_slow_module = create_test_slow_module(
            capability_registry=runtime.capability_registry,
            tool_manager=runtime.tool_manager,
            logger=runtime.logger,
            default_delay=0.0,
        )
        runtime.module_manager.register(test_slow_module)
        runtime.module_manager.load("test_slow")
        
        return runtime

    return _factory


@pytest.fixture(scope="module")
def app_with_slow_module(runtime_factory_with_slow_module):
    """FastAPI app with test_slow module loaded."""
    return create_app(runtime_factory=runtime_factory_with_slow_module)


@pytest.fixture(scope="module")
def client_with_slow_module(app_with_slow_module) -> Iterator[TestClient]:
    """Test client with test_slow module loaded."""
    with TestClient(app_with_slow_module, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _clear_expense_db_with_slow_module(client_with_slow_module, _test_db_pool):
    """Clear the expense database before each test to ensure isolation."""
    from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage
    storage = PostgreSQLExpenseStorage(_test_db_pool)
    storage.initialize()
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.expense;")
            conn.commit()
    storage.shutdown()
    yield