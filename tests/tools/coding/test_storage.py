"""
Unit tests for CodingIndexStorage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.tools.coding.analyzers.python_ast import PythonAstAnalyzer
from parika.tools.coding.exceptions import CodingIndexNotFoundError
from parika.tools.coding.storage import CodingIndexStorage

SOURCE = '''"""Module docstring."""


def helper():
    return 1


def main():
    return helper()


UNUSED_VALUE = 42
'''


@pytest.fixture()
def storage(tmp_path: Path) -> CodingIndexStorage:
    instance = CodingIndexStorage(tmp_path / "coding_index.sqlite3")
    instance.initialize()
    yield instance
    instance.shutdown()


def _parsed(path: str = "mod.py"):
    return PythonAstAnalyzer().parse(Path(path), SOURCE)


def test_upsert_and_symbols_for_file(storage: CodingIndexStorage) -> None:
    parsed = _parsed()
    count = storage.upsert_file(parsed)

    assert count == len(parsed.symbols)

    symbols = storage.symbols_for_file("mod.py")
    names = {symbol.qualified_name for symbol in symbols}
    assert "mod.helper" in names
    assert "mod.main" in names
    assert "mod.UNUSED_VALUE" in names


def test_file_content_hash_round_trips(storage: CodingIndexStorage) -> None:
    parsed = _parsed()
    assert storage.file_content_hash("mod.py") is None

    storage.upsert_file(parsed)
    assert storage.file_content_hash("mod.py") == parsed.content_hash


def test_upsert_file_replaces_previous_symbols(storage: CodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    updated_source = '"""Doc."""\n\n\ndef only_one():\n    return 1\n'
    updated_parsed = PythonAstAnalyzer().parse(Path("mod.py"), updated_source)
    storage.upsert_file(updated_parsed)

    symbols = storage.symbols_for_file("mod.py")
    names = {symbol.qualified_name for symbol in symbols}
    assert names == {"mod", "mod.only_one"}


def test_search_finds_symbol_by_name(storage: CodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    results = storage.search("helper")
    assert any(symbol.qualified_name == "mod.helper" for symbol in results)


def test_find_symbol_raises_when_missing(storage: CodingIndexStorage) -> None:
    with pytest.raises(CodingIndexNotFoundError):
        storage.find_symbol("mod.does_not_exist")


def test_call_edges_resolve_callers_and_callees(storage: CodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    assert "mod.main" in storage.callers_of("mod.helper")
    assert "mod.helper" in storage.callees_of("mod.main")


def test_dead_code_candidates_excludes_referenced_symbols(
    storage: CodingIndexStorage,
) -> None:
    storage.upsert_file(_parsed())

    dead = {symbol.qualified_name for symbol in storage.dead_code_candidates()}
    assert "mod.helper" not in dead  # referenced by mod.main


def test_graph_query_forward_traversal(storage: CodingIndexStorage) -> None:
    storage.upsert_file(_parsed())

    result = storage.graph_query("mod.main", direction="forward", max_depth=2)
    assert "helper" in result.nodes or "mod.helper" in result.nodes


def test_delete_file_removes_all_children(storage: CodingIndexStorage) -> None:
    storage.upsert_file(_parsed())
    storage.delete_file("mod.py")

    assert storage.symbols_for_file("mod.py") == ()
    assert storage.file_content_hash("mod.py") is None
