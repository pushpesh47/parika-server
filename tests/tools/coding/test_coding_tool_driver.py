"""
Integration-style unit tests for CodingToolDriver, covering every
operation end to end against a real PostgreSQL index.
"""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

from pathlib import Path

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.driver import CodingToolDriver
from parika.tools.coding.exceptions import CodingToolError, InvalidCodingArgumentError
from parika.tools.coding.manifest import CodingOperation
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
    yield instance
    instance.shutdown()


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(SOURCE, encoding="utf-8")
    return path


def _driver(
    operation: CodingOperation,
    storage: PostgreSQLCodingIndexStorage,
    *,
    tool_manager=None,
) -> CodingToolDriver:
    return CodingToolDriver(
        operation,
        storage=storage,
        registry=LanguageAnalyzerRegistry(),
        max_file_size_bytes=2_000_000,
        tool_manager=tool_manager,
    )


SOURCE = '''"""Module docstring."""


def helper(value):
    """Return value doubled."""
    return value * 2


def main():
    return helper(1)
'''


def test_parse_indexes_the_file(storage: PostgreSQLCodingIndexStorage, sample_file: Path) -> None:
    driver = _driver(CodingOperation.PARSE, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(sample_file)}))

    assert isinstance(response, ToolResponse)
    assert response.result["symbol_count"] > 0
    assert storage.file_content_hash(str(sample_file)) is not None


def test_symbols_lazily_indexes_on_first_call(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    driver = _driver(CodingOperation.SYMBOLS, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(sample_file)}))

    names = {symbol["qualified_name"] for symbol in response.result}
    assert "sample.helper" in names
    assert "sample.main" in names


def test_search_returns_matches(storage: PostgreSQLCodingIndexStorage, sample_file: Path) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.SEARCH, storage).execute(
        ToolRequest(arguments={"query": "helper"})
    )
    assert any(symbol["qualified_name"] == "sample.helper" for symbol in response.result)


def test_references_returns_call_site(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.REFERENCES, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper"})
    )
    assert any(ref["file_path"] == str(sample_file) for ref in response.result)


def test_callees_returns_called_functions(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.CALLEES, storage).execute(
        ToolRequest(arguments={"symbol": "sample.main"})
    )
    assert "sample.helper" in response.result


def test_callers_returns_calling_functions(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.CALLERS, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper"})
    )
    assert "sample.main" in response.result


def test_imports_returns_imports(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.IMPORTS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )
    assert isinstance(response.result, list)


def test_annotations_returns_annotations(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.ANNOTATIONS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )
    assert isinstance(response.result, list)


def test_dead_code_returns_candidates(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.DEAD_CODE, storage).execute(
        ToolRequest(arguments={})
    )
    # helper is referenced by main, so it shouldn't be in dead code
    dead_names = {item["qualified_name"] for item in response.result}
    assert "sample.helper" not in dead_names
    assert "sample.UNUSED_VALUE" in dead_names


def test_format_rewrites_file(tmp_path: Path, storage: PostgreSQLCodingIndexStorage) -> None:
    source = 'def foo(  ):\n    return 1\n'
    path = tmp_path / "format_test.py"
    path.write_text(source, encoding="utf-8")

    driver = _driver(CodingOperation.FORMAT, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(path)}))

    assert isinstance(response, ToolResponse)
    assert "formatted" in response.result
    # ruff should normalize spacing
    formatted = path.read_text(encoding="utf-8")
    assert "def foo():" in formatted


def test_format_file_not_found(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.FORMAT, storage)
    response = driver.execute(ToolRequest(arguments={"path": "/nonexistent/file.py"}))

    assert isinstance(response, ToolResponse)
    assert response.result["error"] == "File not found"


def test_lint_checks_file(tmp_path: Path, storage: PostgreSQLCodingIndexStorage) -> None:
    source = 'import os\n\ndef foo():\n    x = 1\n    return x\n'
    path = tmp_path / "lint_test.py"
    path.write_text(source, encoding="utf-8")

    driver = _driver(CodingOperation.LINT, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(path)}))

    assert isinstance(response, ToolResponse)
    assert "issues" in response.result
    # Should find unused variable
    issues = response.result["issues"]
    assert any("unused" in issue["message"].lower() for issue in issues)


def test_impact_analysis_returns_graph(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.IMPACT, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper", "direction": "reverse", "max_depth": 2})
    )
    assert "nodes" in response.result
    assert "edges" in response.result
    assert "sample.main" in response.result["nodes"]


def test_project_summary_returns_counts(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.PROJECT_SUMMARY, storage).execute(
        ToolRequest(arguments={"root_prefix": str(sample_file.parent)})
    )
    assert "file_count" in response.result
    assert "symbol_count" in response.result
    assert "languages" in response.result
    assert response.result["file_count"] >= 1


def test_rename_plan_returns_plan(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.RENAME, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper", "new_name": "new_helper"})
    )
    assert "plan" in response.result
    assert "files" in response.result
    assert len(response.result["files"]) >= 1


def test_patch_generates_diff(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.PATCH, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper", "new_name": "new_helper"})
    )
    assert "patch" in response.result
    assert isinstance(response.result["patch"], str)
    assert "sample.helper" in response.result["patch"]
    assert "new_helper" in response.result["patch"]


def test_storage_instance_passed_to_driver(storage: PostgreSQLCodingIndexStorage) -> None:
    """Ensure the same storage instance is used across operations."""
    driver = _driver(CodingOperation.PARSE, storage)
    assert driver.storage is storage


def test_operation_without_storage_raises(tmp_path: Path) -> None:
    driver = _driver(CodingOperation.PARSE, None)  # type: ignore
    response = driver.execute(ToolRequest(arguments={"path": str(tmp_path / "dummy.py")}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Storage not initialized"


def test_invalid_operation_raises(storage: PostgreSQLCodingIndexStorage) -> None:
    with pytest.raises(InvalidCodingArgumentError):
        _driver(CodingOperation("INVALID"), storage)  # type: ignore


def test_parse_missing_path_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.PARSE, storage)
    response = driver.execute(ToolRequest(arguments={}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: path"


def test_format_missing_path_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.FORMAT, storage)
    response = driver.execute(ToolRequest(arguments={}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: path"


def test_lint_missing_path_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.LINT, storage)
    response = driver.execute(ToolRequest(arguments={}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: path"


def test_rename_missing_symbol_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.RENAME, storage)
    response = driver.execute(ToolRequest(arguments={"new_name": "new_name"}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: symbol"


def test_rename_missing_new_name_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.RENAME, storage)
    response = driver.execute(ToolRequest(arguments={"symbol": "foo"}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: new_name"


def test_impact_missing_symbol_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.IMPACT, storage)
    response = driver.execute(ToolRequest(arguments={}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: symbol"


def test_patch_missing_symbol_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.PATCH, storage)
    response = driver.execute(ToolRequest(arguments={"new_name": "new_name"}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: symbol"


def test_patch_missing_new_name_argument(storage: PostgreSQLCodingIndexStorage) -> None:
    driver = _driver(CodingOperation.PATCH, storage)
    response = driver.execute(ToolRequest(arguments={"symbol": "foo"}))
    assert isinstance(response, ToolResponse)
    assert response.result.get("error") == "Missing required argument: new_name"


def test_symbols_with_tool_manager(tmp_path: Path, storage: PostgreSQLCodingIndexStorage) -> None:
    """Test that shell.execute is called for FORMAT/LINT when tool_manager is provided."""
    from unittest.mock import MagicMock
    tool_manager = MagicMock()
    tool_manager.execute.return_value = MagicMock(
        success=True, result={"formatted": True}, error=None
    )

    source = 'def foo(  ):\n    return 1\n'
    path = tmp_path / "format_test.py"
    path.write_text(source, encoding="utf-8")

    driver = _driver(CodingOperation.FORMAT, storage, tool_manager=tool_manager)
    response = driver.execute(ToolRequest(arguments={"path": str(path)}))

    assert isinstance(response, ToolResponse)
    assert tool_manager.execute.called


def test_storage_path_stored_as_string(tmp_path: Path, storage: PostgreSQLCodingIndexStorage) -> None:
    source = 'def foo():\n    return 1\n'
    path = tmp_path / "path_test.py"
    path.write_text(source, encoding="utf-8")

    driver = _driver(CodingOperation.PARSE, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(path)}))

    assert isinstance(response, ToolResponse)
    assert storage.file_content_hash(str(path)) is not None


def test_multiple_files_different_hashes(tmp_path: Path, storage: PostgreSQLCodingIndexStorage) -> None:
    source1 = 'def a():\n    return 1\n'
    source2 = 'def b():\n    return 2\n'
    path1 = tmp_path / "file1.py"
    path2 = tmp_path / "file2.py"
    path1.write_text(source1, encoding="utf-8")
    path2.write_text(source2, encoding="utf-8")

    driver = _driver(CodingOperation.PARSE, storage)
    driver.execute(ToolRequest(arguments={"path": str(path1)}))
    driver.execute(ToolRequest(arguments={"path": str(path2)}))

    hash1 = storage.file_content_hash(str(path1))
    hash2 = storage.file_content_hash(str(path2))

    assert hash1 is not None
    assert hash2 is not None
    assert hash1 != hash2


def test_search_case_insensitive(storage: PostgreSQLCodingIndexStorage, sample_file: Path) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.SEARCH, storage).execute(
        ToolRequest(arguments={"query": "HELPER"})
    )
    assert any(symbol["qualified_name"] == "sample.helper" for symbol in response.result)


def test_search_empty_query(storage: PostgreSQLCodingIndexStorage, sample_file: Path) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.SEARCH, storage).execute(
        ToolRequest(arguments={"query": ""})
    )
    assert response.result == []


def test_search_nonexistent_symbol(storage: PostgreSQLCodingIndexStorage, sample_file: Path) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.SEARCH, storage).execute(
        ToolRequest(arguments={"query": "nonexistent"})
    )
    assert response.result == []


def test_references_case_insensitive(storage: PostgreSQLCodingIndexStorage, sample_file: Path) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.REFERENCES, storage).execute(
        ToolRequest(arguments={"symbol": "SAMPLE.HELPER"})
    )
    assert any(ref["file_path"] == str(sample_file) for ref in response.result)


def test_symbols_returns_full_symbol_info(
    storage: PostgreSQLCodingIndexStorage, sample_file: Path
) -> None:
    driver = _driver(CodingOperation.SYMBOLS, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(sample_file)}))

    for symbol in response.result:
        assert "id" in symbol
        assert "file_path" in symbol
        assert "kind" in symbol
        assert "name" in symbol
        assert "qualified_name" in symbol
        assert "line_start" in symbol
        assert "line_end" in symbol
