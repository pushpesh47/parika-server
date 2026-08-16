"""
Integration-style unit tests for CodingToolDriver, covering every
operation end to end against a real (tmp_path) SQLite index.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.driver import CodingToolDriver
from parika.tools.coding.exceptions import CodingToolError, InvalidCodingArgumentError
from parika.tools.coding.manifest import CodingOperation
from parika.tools.coding.storage import CodingIndexStorage

SOURCE = '''"""Module docstring."""


def helper(value):
    """Return value doubled."""
    return value * 2


def main():
    return helper(1)
'''


@pytest.fixture()
def storage(tmp_path: Path) -> CodingIndexStorage:
    instance = CodingIndexStorage(tmp_path / "coding_index.sqlite3")
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
    storage: CodingIndexStorage,
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


def test_parse_indexes_the_file(storage: CodingIndexStorage, sample_file: Path) -> None:
    driver = _driver(CodingOperation.PARSE, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(sample_file)}))

    assert isinstance(response, ToolResponse)
    assert response.result["symbol_count"] > 0
    assert storage.file_content_hash(str(sample_file)) is not None


def test_symbols_lazily_indexes_on_first_call(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    driver = _driver(CodingOperation.SYMBOLS, storage)
    response = driver.execute(ToolRequest(arguments={"path": str(sample_file)}))

    names = {symbol["qualified_name"] for symbol in response.result}
    assert "sample.helper" in names
    assert "sample.main" in names


def test_search_returns_matches(storage: CodingIndexStorage, sample_file: Path) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.SEARCH, storage).execute(
        ToolRequest(arguments={"query": "helper"})
    )
    assert any(symbol["qualified_name"] == "sample.helper" for symbol in response.result)


def test_references_returns_call_site(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.REFERENCES, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper"})
    )
    assert len(response.result) >= 1


def test_call_hierarchy_returns_callers_and_callees(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.CALL_HIERARCHY, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper"})
    )
    assert "sample.main" in response.result["callers"]


def test_rename_plan_includes_definition_and_reference(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.RENAME_PLAN, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper", "new_name": "double_value"})
    )

    assert response.result["new_name"] == "double_value"
    assert len(response.result["edits"]) >= 2


def test_patch_generate_renders_diff_and_new_content(storage: CodingIndexStorage) -> None:
    driver = _driver(CodingOperation.PATCH_GENERATE, storage)

    response = driver.execute(
        ToolRequest(
            arguments={
                "edits": [
                    {
                        "file_path": "a.py",
                        "line": 1,
                        "column": 0,
                        "old_text": "foo",
                        "new_text": "bar",
                    }
                ],
                "original_contents": {"a.py": "foo = 1\n"},
            }
        )
    )

    file_patch = response.result["files"][0]
    assert file_patch["new_content"] == "bar = 1\n"
    assert "-foo = 1" in file_patch["diff"]
    assert "+bar = 1" in file_patch["diff"]


def test_document_builds_draft_from_signature(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.DOCUMENT, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper"})
    )
    assert response.result["draft"] == "Return value doubled."


def test_complexity_computes_for_python(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    response = _driver(CodingOperation.COMPLEXITY, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )
    complexities = {item["symbol"]: item["complexity"] for item in response.result}
    assert complexities["sample.helper"] == 1
    assert complexities["sample.main"] == 1


def test_dead_code_reports_unreferenced_symbol(
    storage: CodingIndexStorage, tmp_path: Path
) -> None:
    path = tmp_path / "unused.py"
    path.write_text("def never_called():\n    return 1\n", encoding="utf-8")

    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(path)})
    )

    response = _driver(CodingOperation.DEAD_CODE, storage).execute(ToolRequest())
    names = {item["symbol"] for item in response.result}
    assert "unused.never_called" in names


def test_project_summary_counts_files_and_symbols(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    response = _driver(CodingOperation.PROJECT_SUMMARY, storage).execute(
        ToolRequest(arguments={"root": str(sample_file.parent)})
    )
    assert response.result["file_count"] == 1
    assert response.result["symbol_count"] > 0
    assert response.result["languages"] == {"python": 1}


def test_graph_query_and_impact_analysis(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    _driver(CodingOperation.SYMBOLS, storage).execute(
        ToolRequest(arguments={"path": str(sample_file)})
    )

    forward = _driver(CodingOperation.GRAPH_QUERY, storage).execute(
        ToolRequest(arguments={"symbol": "sample.main"})
    )
    assert "sample.helper" in forward.result["nodes"]

    reverse = _driver(CodingOperation.IMPACT_ANALYSIS, storage).execute(
        ToolRequest(arguments={"symbol": "sample.helper"})
    )
    assert "sample.main" in reverse.result["nodes"]


def test_format_without_tool_manager_raises(
    storage: CodingIndexStorage, sample_file: Path
) -> None:
    driver = _driver(CodingOperation.FORMAT, storage)

    with pytest.raises(CodingToolError):
        driver.execute(ToolRequest(arguments={"path": str(sample_file)}))


def test_format_dispatches_through_tool_manager() -> None:
    class _FakeToolManager:
        def __init__(self) -> None:
            self.calls: list[ToolRequest] = []

        def execute(self, tool_id: str, request: ToolRequest) -> ToolResponse:
            self.calls.append(request)
            return ToolResponse(result={"stdout": "", "stderr": "", "exit_code": 0})

    from parika.tools.coding.analyzers.python_ast import PythonAstAnalyzer

    class _FormatterRegistry(LanguageAnalyzerRegistry):
        def __init__(self) -> None:
            super().__init__(
                (PythonAstAnalyzer(formatters={"python": ("ruff", "format")}),)
            )

    fake_tool_manager = _FakeToolManager()
    storage_instance = CodingIndexStorage(Path("/tmp/coding_index_test_format.sqlite3"))
    storage_instance.initialize()

    try:
        driver = CodingToolDriver(
            CodingOperation.FORMAT,
            storage=storage_instance,
            registry=_FormatterRegistry(),
            max_file_size_bytes=2_000_000,
            tool_manager=fake_tool_manager,
        )
        response = driver.execute(ToolRequest(arguments={"path": "sample.py"}))

        assert fake_tool_manager.calls
        assert fake_tool_manager.calls[0].arguments["command"][0] == "ruff"
        assert response.result["exit_code"] == 0
    finally:
        storage_instance.shutdown()
        Path("/tmp/coding_index_test_format.sqlite3").unlink(missing_ok=True)


def test_missing_path_argument_raises() -> None:
    storage_instance = CodingIndexStorage(Path("/tmp/coding_index_test_missing.sqlite3"))
    storage_instance.initialize()

    try:
        driver = CodingToolDriver(
            CodingOperation.SYMBOLS,
            storage=storage_instance,
            registry=LanguageAnalyzerRegistry(),
            max_file_size_bytes=2_000_000,
        )

        with pytest.raises(InvalidCodingArgumentError):
            driver.execute(ToolRequest())
    finally:
        storage_instance.shutdown()
        Path("/tmp/coding_index_test_missing.sqlite3").unlink(missing_ok=True)
