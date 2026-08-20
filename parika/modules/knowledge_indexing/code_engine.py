"""
PARIKA Code Knowledge Engine

KnowledgeEngine for REPOSITORY/WORKSPACE sources: indexes Python
source files by symbol (module docstring, top-level classes/
functions) and by import statements, as searchable Knowledge units.

Symbol/import extraction is delegated to the Coding Tool's
`PythonAstAnalyzer` (`parika.tools.coding.analyzers.python_ast`) rather
than re-implemented here -- a plain library import, not a Module-to-
Module dependency (the Coding Tool package has no Module identity or
driver of its own; this is the same relationship
`FilesystemToolDriver` has to `operations.py`). This removes the
duplicated `ast`-walking logic this engine previously implemented on
its own, per
docs/development/Module_Guide.md section
7.4, while keeping this class's public contract
(`KnowledgeEngine.index()`/`.search()`/`.supports()`) completely
unchanged -- every existing caller and test observes identical
behavior, since `PythonAstAnalyzer` is a strict superset of what this
engine's own extraction used to do; only top-level module docstrings,
classes, and functions are turned into Knowledge units here (methods
and module-level variables are intentionally excluded, matching this
engine's original, narrower scope -- richer symbol-level access is
available through the Coding Tool's own `coding.symbols`/
`coding.search` capabilities, see section 4).

Richer multi-language symbol extraction (e.g. via tree-sitter) is now
implemented by the Coding Tool's `TreeSitterAnalyzer` as a documented
optional extra -- see
docs/development/Module_Guide.md section
4.4.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from parika.core.knowledge_manager.engine import KnowledgeEngine
from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.search_result import SearchResult
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.modules._shared.content_hash import iter_files
from parika.tools.coding.analyzers.python_ast import PythonAstAnalyzer
from parika.tools.coding.model import ParsedFile, SymbolKind
from .postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage, build_knowledge_unit

_SUPPORTED_KINDS = (
    KnowledgeSourceKind.REPOSITORY,
    KnowledgeSourceKind.WORKSPACE,
)

_TOP_LEVEL_SYMBOL_KINDS = (SymbolKind.MODULE, SymbolKind.CLASS, SymbolKind.FUNCTION)


class CodeKnowledgeEngine(KnowledgeEngine):
    """
    Indexes Python source files by symbol (class/function/module) and
    by import statements, delegating parsing to `PythonAstAnalyzer`.
    """

    def __init__(self, unit_storage: PostgreSQLKnowledgeUnitStorage) -> None:
        self._unit_storage = unit_storage
        self._analyzer = PythonAstAnalyzer()

    def supports(self, source: KnowledgeSource) -> bool:
        return source.kind in _SUPPORTED_KINDS

    def index(self, source: KnowledgeSource) -> int:
        root = Path(source.location)
        units: list[Knowledge] = []

        for path in iter_files(root, suffixes=(".py",)):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            parsed = self._analyzer.parse(path, text)

            if parsed.diagnostics:
                # Syntax-invalid files are skipped, matching this
                # engine's original behavior.
                continue

            units.extend(_extract_units(source.id, parsed))

        return self._unit_storage.replace_units_for_source(source.id, units)

    def remove(self, source: KnowledgeSource) -> None:
        self._unit_storage.delete_units_for_source(source.id)

    def search(
        self, sources: tuple[KnowledgeSource, ...], query: SearchQuery
    ) -> tuple[SearchResult, ...]:
        return self._unit_storage.search(
            source_ids=frozenset(source.id for source in sources),
            text=query.text,
            limit=query.limit + query.offset,
        )


def _extract_units(source_id: UUID, parsed: ParsedFile) -> list[Knowledge]:
    units: list[Knowledge] = []
    path = Path(parsed.file_path)

    import_names = sorted(
        {
            f"{edge.imported_module}.{edge.imported_symbol}"
            if edge.imported_symbol
            else edge.imported_module
            for edge in parsed.imports
        }
    )

    if import_names:
        units.append(
            build_knowledge_unit(
                source_id=source_id,
                title=f"{path.stem} (imports)",
                content="\n".join(import_names),
                location=f"{path}:1",
                metadata={"symbol_kind": "imports"},
            )
        )

    for symbol in parsed.symbols:
        if symbol.kind not in _TOP_LEVEL_SYMBOL_KINDS:
            continue

        if symbol.kind is SymbolKind.MODULE:
            if not symbol.docstring:
                continue

            units.append(
                build_knowledge_unit(
                    source_id=source_id,
                    title=f"{path.stem} (module)",
                    content=symbol.docstring,
                    location=f"{path}:{symbol.line_start}",
                    metadata={"symbol_kind": "module"},
                )
            )
            continue

        signature = symbol.signature or symbol.name
        content = f"{signature}\n\n{symbol.docstring or ''}".strip() or signature

        units.append(
            build_knowledge_unit(
                source_id=source_id,
                title=symbol.qualified_name,
                content=content,
                location=f"{path}:{symbol.line_start}",
                metadata={"symbol_kind": symbol.kind.value},
            )
        )

    return units
