"""
PARIKA Test - Conftest with Slow Module

Extended test configuration that includes the test_slow module for
concurrency testing.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import os

import pytest
from fastapi.testclient import TestClient

from parika.interfaces.runtime import ParikaRuntime, build_default_runtime
from parika.server.app import create_app
from parika.tools.expense.storage import ExpenseStorage
from parika.tools.test_slow.module import TestSlowModule


@pytest.fixture(scope="module")
def runtime_factory_with_slow_module(tmp_path_factory):
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
        )
        
        # Register and load the test slow module
        test_slow_module = TestSlowModule(default_delay=0.0)
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
def _clear_expense_db_with_slow_module(client_with_slow_module, tmp_path_factory, request):
    """Clear the expense database before each test to ensure isolation."""
    base_temp = tmp_path_factory.getbasetemp()
    
    # The test data directory is created by tmp_path_factory.mktemp("parika-api-data")
    found_dir = False
    for root, dirs, files in os.walk(base_temp):
        for d in dirs:
            if 'parika-api-data' in d:
                data_dir = Path(root) / d
                found_dir = True
                db_path = data_dir / "expense.sqlite3"
                if db_path.exists():
                    storage = ExpenseStorage(db_path)
                    storage.initialize()
                    storage._connection.execute("DELETE FROM expenses;")
                    storage._connection.commit()
                    storage.shutdown()
                else:
                    # Ensure database exists for tests that run before any API request
                    storage = ExpenseStorage(db_path)
                    storage.initialize()
                    storage.shutdown()
    if not found_dir:
        pass  # No parika-api-data directory found
    yield