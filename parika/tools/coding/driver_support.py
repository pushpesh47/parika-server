"""
PARIKA Coding Tool - Driver Support

Pure(ish) helper functions used by `CodingToolDriver`, kept in their
own module so `driver.py` stays a thin per-operation dispatcher (Coding
Standards' file-size guideline). Every function here still performs
only read-only filesystem access (reading a file's own text, never
writing) and index storage reads/writes -- never Filesystem/Shell Tool
dispatch, which stays in `driver.py` itself (the only place that needs
a `ToolManager` reference).
"""

from __future__ import annotations

import re
from pathlib import Path

from parika.tools.coding.analysis.complexity import compute_python_complexity
from parika.tools.coding.analysis.dead_code import find_dead_code
from parika.tools.coding.analysis.duplicates import find_duplicate_groups
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.exceptions import (
    InvalidCodingArgumentError,
    UnsupportedLanguageError,
)
from parika.tools.coding.model import (
    ComplexityResult,
    DeadCodeCandidate,
    DuplicateGroup,
    ImportEdge,
    ParsedFile,
    ProjectSummaryResult,
    Symbol,
)
from parika.tools.coding.storage import CodingIndexStorage

_ARG_PATTERN = re.compile(r"\(([^)]*)\)")


def ensure_indexed(
    storage: CodingIndexStorage,
    registry: LanguageAnalyzerRegistry,
    path: Path,
    *,
    max_file_size_bytes: int,
) -> ParsedFile:
    """
    Parse and store `path`'s index only if its content changed since
    the last index pass (content-hash-gated incremental indexing, see
    docs/development/Tool_Guide.md
    section 7.3). Always returns the freshly (or previously) parsed
    result read back from disk.
    """

    if path.stat().st_size > max_file_size_bytes:
        raise InvalidCodingArgumentError(
            f"'{path}' exceeds [coding].max_file_size_bytes "
            f"({max_file_size_bytes}); it was not indexed."
        )

    text = path.read_text(encoding="utf-8", errors="replace")
    analyzer = registry.resolve(path)
    parsed = analyzer.parse(path, text)

    stored_hash = storage.file_content_hash(str(path))

    if stored_hash != parsed.content_hash:
        storage.upsert_file(parsed)

    return parsed


def build_rename_edits(
    storage: CodingIndexStorage, qualified_name: str, new_name: str
) -> tuple[Symbol, list[dict[str, object]]]:
    symbol = storage.find_symbol(qualified_name)
    references = storage.references_to(qualified_name)

    edits: list[dict[str, object]] = [
        {
            "file_path": symbol.file_path,
            "line": symbol.line_start,
            "column": 0,
            "old_text": symbol.name,
            "new_text": new_name,
        }
    ]

    for reference in references:
        edits.append(
            {
                "file_path": reference.file_path,
                "line": reference.line,
                "column": reference.column,
                "old_text": symbol.name,
                "new_text": new_name,
            }
        )

    return symbol, edits


def build_document_draft(symbol: Symbol) -> str:
    """
    Build a deterministic docstring draft from a symbol's signature --
    never an LLM call (see
    docs/development/Tool_Guide.md
    section 4.8).
    """

    if symbol.docstring:
        return symbol.docstring

    args = _extract_arg_names(symbol.signature or "")
    lines = [f"{symbol.name}.", ""]

    if args:
        lines.append("Args:")
        for arg in args:
            if arg in ("self", "cls"):
                continue
            lines.append(f"    {arg}: TODO describe '{arg}'.")

    return "\n".join(lines).strip()


def _extract_arg_names(signature: str) -> list[str]:
    match = _ARG_PATTERN.search(signature)

    if not match:
        return []

    return [
        argument.split(":")[0].split("=")[0].strip()
        for argument in match.group(1).split(",")
        if argument.strip()
    ]


def deduplicated_dependencies(imports: tuple[ImportEdge, ...]) -> tuple[str, ...]:
    seen: list[str] = []

    for edge in imports:
        name = (
            f"{edge.imported_module}.{edge.imported_symbol}"
            if edge.imported_symbol
            else edge.imported_module
        )

        if name not in seen:
            seen.append(name)

    return tuple(seen)


def compute_complexity_for_path(path: Path, language: str) -> tuple[ComplexityResult, ...]:
    if language != "python":
        raise UnsupportedLanguageError(
            f"Complexity analysis is implemented for Python only in this "
            f"phase; '{language}' is not supported yet."
        )

    text = path.read_text(encoding="utf-8", errors="replace")

    return compute_python_complexity(text, str(path))


def compute_duplicates_for_paths(
    storage: CodingIndexStorage,
    paths: list[Path],
    *,
    similarity_threshold: float,
) -> tuple[DuplicateGroup, ...]:
    symbols_with_source: list[tuple[Symbol, str]] = []

    for path in paths:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        for symbol in storage.symbols_for_file(str(path)):
            start = max(symbol.line_start - 1, 0)
            end = min(symbol.line_end, len(lines))
            source = "\n".join(lines[start:end])
            symbols_with_source.append((symbol, source))

    return find_duplicate_groups(
        symbols_with_source, similarity_threshold=similarity_threshold
    )


def compute_dead_code(storage: CodingIndexStorage) -> tuple[DeadCodeCandidate, ...]:
    return find_dead_code(storage)


def build_project_summary(
    storage: CodingIndexStorage, root: str
) -> ProjectSummaryResult:
    file_count, symbol_count, languages = storage.summary_for_prefix(root)

    return ProjectSummaryResult(
        root=root,
        file_count=file_count,
        symbol_count=symbol_count,
        languages=languages,
    )
