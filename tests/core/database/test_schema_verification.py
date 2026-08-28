"""
Schema verification tests to prevent database/production mismatches.

These tests ensure that every PostgreSQL-backed storage/cache implementation
references tables that actually exist in the migrated schema.
"""

from __future__ import annotations

import pytest

from parika.core.database.pool import PoolManager
from parika.tools.web_search.postgresql_cache import PostgreSQLSearchResultCache
from parika.tools.weather.postgresql_cache import PostgreSQLWeatherCache
from parika.tools.expense.postgresql_storage import PostgreSQLExpenseStorage
from parika.tools.coding.postgresql_storage import PostgreSQLCodingIndexStorage
from parika.modules.knowledge_indexing.postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage
from parika.modules.experience.postgresql_storage import PostgreSQLExperienceStorage
from parika.core.knowledge_manager.postgresql_storage import PostgreSQLKnowledgeStorage
from parika.core.memory_manager.postgresql_storage import PostgreSQLMemoryStorage
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore
from tests.conftest_db import build_test_db_config


@pytest.fixture(scope="session")
def test_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


def test_web_search_cache_table_exists(test_pool):
    """Verify cache.web_search table exists (migration) and is used by code."""
    cache = PostgreSQLSearchResultCache(test_pool)
    cache.initialize()
    try:
        # This will fail if table doesn't exist
        result = cache.get("test_key_that_does_not_exist")
        assert result is None
    finally:
        cache.shutdown()


def test_weather_cache_table_exists(test_pool):
    """Verify cache.weather table exists and is used by code."""
    cache = PostgreSQLWeatherCache(test_pool)
    cache.initialize()
    try:
        result = cache.get_cached("test_key")
        assert result is None
    finally:
        cache.shutdown()


def test_expense_table_exists(test_pool):
    """Verify core.expense table exists and is used by code."""
    storage = PostgreSQLExpenseStorage(test_pool)
    storage.initialize()
    try:
        result = storage.get("nonexistent")
        assert result is None
    finally:
        storage.shutdown()


def test_coding_tables_exist(test_pool):
    """Verify coding schema tables exist and are used by code."""
    storage = PostgreSQLCodingIndexStorage(test_pool)
    storage.initialize()
    try:
        result = storage.file_content_hash("nonexistent.py")
        assert result is None
    finally:
        storage.shutdown()


def test_knowledge_unit_table_exists(test_pool):
    """Verify coding.knowledge_unit table exists and is used by code."""
    storage = PostgreSQLKnowledgeUnitStorage(test_pool)
    storage.initialize()
    try:
        from uuid import uuid4
        result = storage.search(source_ids=frozenset({uuid4()}), text="test", limit=10)
        assert result == ()
    finally:
        storage.shutdown()


def test_experience_table_exists(test_pool):
    """Verify core.experience table exists and is used by code."""
    storage = PostgreSQLExperienceStorage(test_pool)
    storage.initialize()
    try:
        result = storage.get("nonexistent")
        assert result is None
    finally:
        storage.shutdown()


def test_knowledge_source_table_exists(test_pool):
    """Verify core.knowledge_source table exists and is used by code."""
    storage = PostgreSQLKnowledgeStorage(test_pool)
    storage.initialize()
    try:
        from uuid import uuid4
        result = storage.contains(uuid4())
        assert result is False
    finally:
        storage.shutdown()


def test_memory_table_exists(test_pool):
    """Verify core.memory table exists and is used by code."""
    storage = PostgreSQLMemoryStorage(test_pool)
    storage.initialize()
    try:
        result = storage.get("nonexistent")
        assert result is None
    finally:
        storage.shutdown()


def test_session_tables_exist(test_pool):
    """Verify core.session and core.session_message tables exist and are used by code."""
    storage = PostgreSQLSessionStore(test_pool)
    storage.initialize()
    try:
        result = storage.get_session("nonexistent")
        assert result is None
    finally:
        storage.shutdown()


def test_all_expected_tables_exist(test_pool):
    """Verify all expected tables exist in the database."""
    expected_tables = {
        "core": [
            "memory",
            "memory_metadata",
            "knowledge_source",
            "knowledge_source_metadata",
            "experience",
            "experience_metadata",
            "session",
            "session_message",
            "expense",
            "expense_metadata",
        ],
        "coding": [
            "knowledge_unit",
            "coding_files",
            "coding_symbols",
            "coding_references",
            "coding_imports",
            "coding_call_edges",
            "coding_annotations",
        ],
        "cache": [
            "weather",
            "web_search",
        ],
        "agent": [
            "agent_profile",
        ],
        "execution": [
            "execution_goal",
        ],
    }

    with test_pool.connection() as conn:
        with conn.cursor() as cur:
            for schema, tables in expected_tables.items():
                for table in tables:
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s);",
                        (schema, table),
                    )
                    exists = cur.fetchone()[0]
                    assert exists, f"Table {schema}.{table} does not exist in database"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])