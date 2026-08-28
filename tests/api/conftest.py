"""
Shared fixtures for `tests/api/`.

Builds a real `ParikaRuntime` (via the existing, unmodified
`build_default_runtime()`) against an isolated data directory, with
Ollama model discovery disabled so the suite never depends on real
network access or a running Ollama server -- the same isolation
convention already used by `tests/integration/test_chat_pipeline.py`
and by `build_default_runtime()`'s own documented `data_directory`
override.

`runtime_factory`/`app`/`client` are module-scoped: one full
`ParikaRuntime` (which loads all 14 Modules, ~50 Tools/capabilities,
and PostgreSQL-backed stores) is comparatively expensive to
construct and tear down. Building one per test *function* (the
original implementation) multiplied that cost by the number of tests
and measurably increased total suite wall-clock time and short-lived
thread churn -- which, investigated as part of resolving a flaky
pre-existing test (`tests/core/scheduler/test_scheduler.py::TestShutdown
::test_shutdown_cancels_all_scheduled_jobs`, a real-time-sensitive
Scheduler test unrelated to and never modified by Phase 3.5), was the
root cause of that test occasionally missing its 0.2s/0.3s timing
windows under the added system load. Sharing one runtime per test
*module* (file) instead cuts the number of full `ParikaRuntime`
constructions in this package from one-per-test to one-per-file,
removing that load, without weakening any assertion in any test.

Additional fixtures for concurrency testing with test_slow module.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import os

import pytest
from fastapi.testclient import TestClient

from parika.interfaces.runtime import ParikaRuntime, build_default_runtime
from parika.server.app import create_app
from parika.tools.test_slow import create_test_slow_module
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.logger.logger import Logger
from parika.core.database.pool import PoolManager
from parika.core.database.config import DatabaseConfig


def _build_test_db_config() -> DatabaseConfig:
    """Build test database configuration from environment variables."""
    return DatabaseConfig(
        enabled=True,
        host=os.environ.get("PARIKA_TEST_DATABASE__HOST", "127.0.0.1"),
        port=int(os.environ.get("PARIKA_TEST_DATABASE__PORT", "5432")),
        database=os.environ.get("PARIKA_TEST_DATABASE__NAME", "parika_test"),
        username=os.environ.get("PARIKA_TEST_DATABASE__USERNAME", ""),
        password=os.environ.get("PARIKA_TEST_DATABASE__PASSWORD", ""),
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
    db_config = _build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture(scope="module")
def runtime_factory(_test_db_pool, tmp_path_factory):
    data_directory = tmp_path_factory.mktemp("parika-api-data")

    def _factory(sync_pool=None) -> ParikaRuntime:
        # Use provided sync_pool or fallback to test pool
        pool = sync_pool if sync_pool is not None else _test_db_pool
        return build_default_runtime(
            discover_ollama_models=False,
            discover_comfyui_models=False,
            load_modules=True,
            data_directory=data_directory,
            sync_pool=pool,
        )

    return _factory


@pytest.fixture(scope="module")
def app(runtime_factory):
    return create_app(runtime_factory=runtime_factory)


@pytest.fixture(scope="module")
def client(app) -> Iterator[TestClient]:
    # `raise_server_exceptions=False`: Starlette's `ServerErrorMiddleware`
    # re-raises every exception into the ASGI caller for logging purposes
    # even after a registered `app.exception_handler(Exception)` (section
    # 14.2) has already produced the correct JSON error response --
    # `TestClient`'s own `raise_server_exceptions=True` default additionally
    # surfaces that re-raise as a test failure. Disabling it here lets these
    # tests assert on the actual HTTP response the real deployed server
    # would send, exactly as `parika/api/errors.py` builds it.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


# Concurrency testing fixtures with test_slow module
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
def _clear_expense_db(client, _test_db_pool):
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


@pytest.fixture(autouse=True)
def _clear_expense_db_with_slow_module(client_with_slow_module, _test_db_pool):
    """Clear the expense database before each test to ensure isolation (for slow module tests)."""
    from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage
    storage = PostgreSQLExpenseStorage(_test_db_pool)
    storage.initialize()
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.expense;")
            conn.commit()
    storage.shutdown()
    yield