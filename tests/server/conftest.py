"""
Shared fixtures for `tests/server/`. Mirrors `tests/api/conftest.py`
(both need the same isolated-runtime-factory convention); kept as a
short, separate file rather than a cross-directory import because
pytest fixtures do not cross sibling `conftest.py` boundaries.
"""

from __future__ import annotations

import pytest

from parika.interfaces.runtime import ParikaRuntime, build_default_runtime
from parika.core.database.config import DatabaseConfig


# Session-scoped autouse fixture to disable PostgreSQL for all tests
# This must be applied before any module imports that use load_database_config
@pytest.fixture(scope="session", autouse=True)
def _disable_postgresql_for_tests():
    """Disable PostgreSQL for all tests by patching load_database_config."""
    import parika.core.database.config as db_config_module
    original_load = db_config_module.load_database_config
    
    def patched_load(configuration):
        cfg = original_load(configuration)
        return DatabaseConfig(
            enabled=False,
            host=cfg.host,
            port=cfg.port,
            database=cfg.database,
            username=cfg.username,
            password=cfg.password,
            pool_min_size=cfg.pool_min_size,
            pool_max_size=cfg.pool_max_size,
            connect_timeout=cfg.connect_timeout,
            statement_timeout=cfg.statement_timeout,
            application_name=cfg.application_name,
        )
    
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