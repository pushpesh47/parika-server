"""
Unit tests for PostgreSQLCodingIndexStorage.
"""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

from pathlib import Path

import pytest

from parika.tools.coding.analyzers.python_ast import PythonAstAnalyzer
from parika.tools.coding.exceptions import CodingIndexNotFoundError
from parika.tools.coding.postgresql_storage import PostgreSQLCodingIndexStorage
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module
from parika.core.database.config import DatabaseConfig


# Test database configuration
# Test database configuration from environment
# TEST_DATABASE_CONFIG = { ... }  # Replaced by build_test_db_config()


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture()
def storage(_test_db_pool) -> PostgreSQLCodingIndexStorage:
    instance = PostgreSQLCodingIndexStorage(_test_db_pool)
    instance.initialize()
    # Clean up before test
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coding.coding_call_edges;")
            cur.execute("DELETE FROM coding.coding_references;")
            cur.execute("DELETE FROM coding.coding_imports;")
            cur.execute("DELETE FROM coding.coding_annotations;")
            cur.execute("DELETE FROM coding.coding_symbols;")
            cur.execute("DELETE FROM coding.coding_files;")
            conn.commit()
    yield instance
    # Clean up after test
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coding.coding_call_edges;")
            cur.execute("DELETE FROM coding.coding_references;")
            cur.execute("DELETE FROM coding.coding_imports;")
            cur.execute("DELETE FROM coding.coding_annotations;")
            cur.execute("DELETE FROM coding.coding_symbols;")
            cur.execute("DELETE FROM coding.coding_files;")
            conn.commit()
    instance.shutdown()


SOURCE = '''"""Module docstring."""


def helper():
    return 1


def main():
    return helper()


UNUSED_VALUE = 42
'''


def _parsed(path: str = "mod.py"):
    return PythonAstAnalyzer().parse(Path(path), SOURCE)


def test_upsert_and_symbols_for_file(storage: PostgreSQLCodingIndexStorage) -> None:
    parsed = _parsed()
    count = storage.upsert_file(parsed)

    assert count == len(parsed.symbols)

    symbols = storage.symbols_for_file("mod.py")
    names = {symbol.qualified_name for symbol in symbols}
    assert "mod.helper" in names
    assert "mod.main" in names
    assert "mod.UNUSED_VALUE" in names


def test_file_content_hash_round_trips(storage: PostgreSQLCodingIndexStorage) -> None:
    parsed = _parsed()
    assert storage.file_content_hash("mod.py") is None

    storage.upsert_file(parsed)
    assert storage.file_content_hash("mod.py") == parsed.content_hash


def test_upsert_file_replaces_previous_symbols(storage: PostgreSQLCodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    updated_source = '"""Doc."""\n\n\ndef only_one():\n    return 1\n'
    updated_parsed = PythonAstAnalyzer().parse(Path("mod.py"), updated_source)
    storage.upsert_file(updated_parsed)

    symbols = storage.symbols_for_file("mod.py")
    names = {symbol.qualified_name for symbol in symbols}
    assert names == {"mod", "mod.only_one"}


def test_search_finds_symbol_by_name(storage: PostgreSQLCodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    results = storage.search("helper")
    assert any(symbol.qualified_name == "mod.helper" for symbol in results)


def test_find_symbol_raises_when_missing(storage: PostgreSQLCodingIndexStorage) -> None:
    with pytest.raises(CodingIndexNotFoundError):
        storage.find_symbol("mod.does_not_exist")


def test_call_edges_resolve_callers_and_callees(storage: PostgreSQLCodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    assert "mod.main" in storage.callers_of("mod.helper")
    assert "mod.helper" in storage.callees_of("mod.main")


def test_dead_code_candidates_excludes_referenced_symbols(
    storage: PostgreSQLCodingIndexStorage,
) -> None:
    storage.upsert_file(_parsed())

    dead = {symbol.qualified_name for symbol in storage.dead_code_candidates()}
    assert "mod.helper" not in dead  # referenced by mod.main


def test_graph_query_forward_traversal(storage: PostgreSQLCodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    result = storage.graph_query("mod.main", direction="forward", max_depth=2)
    assert "helper" in result.nodes or "mod.helper" in result.nodes


def test_delete_file_removes_all_children(storage: PostgreSQLCodingIndexStorage) -> None:
    storage.upsert_file(_parsed())
    storage.delete_file("mod.py")

    assert storage.symbols_for_file("mod.py") == ()
    assert storage.file_content_hash("mod.py") is None
