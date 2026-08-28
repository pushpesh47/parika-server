"""
Shared fixtures for `tests/server/`. Mirrors `tests/api/conftest.py`
(both need the same isolated-runtime-factory convention); kept as a
short, separate file rather than a cross-directory import because
pytest fixtures do not cross sibling `conftest.py` boundaries.
"""

from __future__ import annotations

import os
import pytest

from parika.interfaces.runtime import ParikaRuntime, build_default_runtime
from parika.core.database.config import DatabaseConfig


def _build_test_db_config() -> DatabaseConfig:
    """Build test database configuration from environment variables."""
    return DatabaseConfig(
        enabled=False,
        host=os.environ.get("PARIKA_TEST_DATABASE__HOST", "127.0.0.1"),
        port=int(os.environ.get("PARIKA_TEST_DATABASE__PORT", "5432")),
        database=os.environ.get("PARIKA_TEST_DATABASE__NAME", "parika_test"),
        username=os.environ.get("PARIKA_TEST_DATABASE__USERNAME", ""),
        password=os.environ.get("PARIKA_TEST_DATABASE__PASSWORD", ""),
        pool_min_size=2,
        pool_max_size=10,
        connect_timeout=10.0,
        statement_timeout=0.0,
        application_name="parika_test",
    )


# Session-scoped autouse fixture to disable PostgreSQL for tests
# This must be applied before any module imports that use load_database_config
@pytest.fixture(scope="session", autouse=True)
def _disable_postgresql_for_tests():
    """Disable PostgreSQL for all tests by patching load_database_config."""
    import parika.core.database.config as db_config_module
    original_load = db_config_module.load_database_config
    
    def patched_load(configuration):
        return _build_test_db_config()
    
    db_config_module.load_database_config = patched_load
    yield
    # Restore original function after all tests
    db_config_module.load_database_config = original_load


@pytest.fixture
def runtime_factory(tmp_path):
    def _factory() -> ParikaRuntime:
        return build_default_runtime(
            discover_ollama_models=False,
            discover_comfyui_models=False,
            load_modules=True,
            data_directory=tmp_path,
        )

    return _factory