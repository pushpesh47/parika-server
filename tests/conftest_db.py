"""
Shared database test configuration utilities.

Provides a centralized way to build test database configuration from
environment variables, avoiding hardcoded values in test files.
"""

from __future__ import annotations

import os

from parika.core.database.config import DatabaseConfig


def build_test_db_config(
    *,
    application_name: str = "parika_test",
    pool_min_size: int = 2,
    pool_max_size: int = 10,
    connect_timeout: float = 10.0,
    statement_timeout: float = 0.0,
    sslmode: str = "prefer",
    enabled: bool = True,
) -> DatabaseConfig:
    """
    Build a DatabaseConfig for tests from environment variables.

    Uses PARIKA_TEST_DATABASE__* environment variables with sensible defaults.
    """
    return DatabaseConfig(
        enabled=enabled,
        host=os.environ.get("PARIKA_TEST_DATABASE__HOST", "127.0.0.1"),
        port=int(os.environ.get("PARIKA_TEST_DATABASE__PORT", "5432")),
        database=os.environ.get("PARIKA_TEST_DATABASE__NAME", "parika_test"),
        username=os.environ.get("PARIKA_TEST_DATABASE__USERNAME", ""),
        password=os.environ.get("PARIKA_TEST_DATABASE__PASSWORD", ""),
        pool_min_size=pool_min_size,
        pool_max_size=pool_max_size,
        connect_timeout=connect_timeout,
        statement_timeout=statement_timeout,
        application_name=application_name,
        sslmode=sslmode,
    )