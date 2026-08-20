"""
PARIKA Coding Tool - Driver

Implements the `ToolDriver` contract
(`parika.core.tool_manager.driver.ToolDriver`) for every Coding Tool
operation.

A single `CodingToolDriver` instance is bound to exactly one
`CodingOperation` at construction time, mirroring
`FilesystemToolDriver`/`ShellToolDriver` (see `manifest.py`'s module
docstring for why one Tool per Capability is required here). The
`coding` Module constructs one instance per operation and registers
each as its own Tool.

The Coding Tool is never a filesystem tool: every operation is
read-only with respect to source files (it reads a file's own text
directly, the same "engine reads its own source content directly"
precedent already established by `CodeKnowledgeEngine`/
`DocumentKnowledgeEngine`) and never writes one. `coding.format`/
`coding.lint` are the only operations that cause any external side
effect, and they do so exclusively by dispatching to the existing,
unmodified Shell Tool through `ToolManager.execute()` -- never by
spawning a process themselves. See
docs/development/Tool_Guide.md section 4
for the full design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import driver_support as support
from .analyzers.registry import LanguageAnalyzerRegistry
from .exceptions import (
    CodingToolError,
    InvalidCodingArgumentError,
)
from .manifest import CodingOperation
from .patch import render_patch
from .postgresql_storage import PostgreSQLCodingIndexStorage

SHELL_EXECUTE_TOOL_ID = "tool.shell_execute"


class CodingToolDriver:
    """
    ToolDriver implementing one Coding Tool operation.
    """

    def __init__(
        self,
        operation: CodingOperation,
        *,
        storage: PostgreSQLCodingIndexStorage,
        registry: LanguageAnalyzerRegistry,
        max_file_size_bytes: int,
        tool_manager: ToolManager | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        """
        Initialize the driver for one operation.

        Args:
            operation:
                The single `CodingOperation` this driver instance
                implements.

            storage:
                Shared `CodingIndexStorage` every operation reads from
                (and, for `PARSE`/index-populating operations, writes
                to).

            registry:
                Shared `LanguageAnalyzerRegistry` used to resolve a
                path to its `LanguageAnalyzer`.

            max_file_size_bytes:
                Upper bound on a single file's size for indexing
                operations.

            tool_manager:
                Optional `ToolManager`, required only by `FORMAT`/
                `LINT` to dispatch to the existing Shell Tool's
                `shell.execute` capability. Omitting it makes those
                two operations raise a clear `CodingToolError` instead
                of silently doing nothing.

            progress_reporter:
                Optional `ProgressReporter` this operation reports its
                own real progress through (see
                docs/development/Tool_Guide.md
                Addendum A/B). Defaults to a no-op
                `NullProgressReporter` bound to this operation's own
                Capability id.
        """

        self._operation = operation
        self._storage = storage
        self._registry = registry
        self._max_file_size_bytes = max_file_size_bytes
        self._tool_manager = tool_manager
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter(f"coding.{operation.value}")
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute this driver's bound operation.

        Raises:
            InvalidCodingArgumentError:
                If a required argument is missing or invalid.

            UnsupportedLanguageError:
                If the resolved analyzer cannot satisfy this
                operation for the target file's language.

            LanguageAnalyzerUnavailableError:
                If a Tree-sitter-backed analyzer is required but the
                optional dependency group is not installed.

            CodingIndexNotFoundError:
                If a query targets a file/symbol never indexed.

            PatchGenerationError:
                If a patch cannot be rendered from the supplied edits.

            CodingToolError:
                If `FORMAT`/`LINT` is invoked without a `ToolManager`.
        """

        self._progress.started(message=_STARTED_MESSAGES.get(self._operation))

        try:
            result = self._dispatch(request)

        except Exception:
            self._progress.failed()
            raise

        self._progress.completed()

        return result

    def _dispatch(self, request: ToolRequest) -> ToolResponse:
        match self._operation:
            case CodingOperation.PARSE:
                return self._execute_parse(request)
            case CodingOperation.SYMBOLS:
                return self._execute_symbols(request)
            case CodingOperation.SEARCH:
                return self._execute_search(request)
            case CodingOperation.REFERENCES:
                return self._execute_references(request)
            case CodingOperation.CALL_HIERARCHY:
                return self._execute_call_hierarchy(request)
            case CodingOperation.IMPORTS:
                return self._execute_imports(request)
            case CodingOperation.DEPENDENCIES:
                return self._execute_dependencies(request)
            case CodingOperation.RENAME_PLAN:
                return self._execute_rename_plan(request)
            case CodingOperation.REFACTOR_PLAN:
                return self._execute_refactor_plan(request)
            case CodingOperation.PATCH_GENERATE:
                return self._execute_patch_generate(request)
            case CodingOperation.DOCUMENT:
                return self._execute_document(request)
            case CodingOperation.FORMAT:
                return self._execute_format(request)
            case CodingOperation.LINT:
                return self._execute_lint(request)
            case CodingOperation.COMPLEXITY:
                return self._execute_complexity(request)
            case CodingOperation.DUPLICATES:
                return self._execute_duplicates(request)
            case CodingOperation.DEAD_CODE:
                return self._execute_dead_code(request)
            case CodingOperation.PROJECT_SUMMARY:
                return self._execute_project_summary(request)
            case CodingOperation.GRAPH_QUERY:
                return self._execute_graph_query(request)
            case CodingOperation.IMPACT_ANALYSIS:
                return self._execute_impact_analysis(request)

        raise InvalidCodingArgumentError(
            f"Unknown Coding Tool operation: {self._operation!r}."
        )

    # ------------------------------------------------------------------
    # Indexing / read operations
    # ------------------------------------------------------------------

    def _execute_parse(self, request: ToolRequest) -> ToolResponse:
        path = self._require_path(request)
        parsed = support.ensure_indexed(
            self._storage,
            self._registry,
            path,
            max_file_size_bytes=self._max_file_size_bytes,
        )

        return ToolResponse(
            result={
                "file_path": parsed.file_path,
                "language": parsed.language,
                "symbol_count": len(parsed.symbols),
                "import_count": len(parsed.imports),
                "diagnostics": [
                    {"message": d.message, "line": d.line, "severity": d.severity}
                    for d in parsed.diagnostics
                ],
            },
            attributes={"path": str(path)},
        )

    def _execute_symbols(self, request: ToolRequest) -> ToolResponse:
        path = self._require_path(request)
        support.ensure_indexed(
            self._storage,
            self._registry,
            path,
            max_file_size_bytes=self._max_file_size_bytes,
        )
        symbols = self._storage.symbols_for_file(str(path))

        return ToolResponse(
            result=[_symbol_to_dict(symbol) for symbol in symbols],
            attributes={"path": str(path), "count": len(symbols)},
        )

    def _execute_search(self, request: ToolRequest) -> ToolResponse:
        text = str(request.arguments.get("query", "")).strip()

        if not text:
            raise InvalidCodingArgumentError(
                "request.arguments['query'] must be a non-empty string."
            )

        limit = int(request.arguments.get("limit", 20))
        symbols = self._storage.search(text, limit=limit)
        self._progress.progress(current=len(symbols), message=f"{len(symbols)} matches found")

        return ToolResponse(
            result=[_symbol_to_dict(symbol) for symbol in symbols],
            attributes={"query": text, "count": len(symbols)},
        )

    def _execute_references(self, request: ToolRequest) -> ToolResponse:
        qualified_name = self._require_symbol(request)
        references = self._storage.references_to(qualified_name)

        return ToolResponse(
            result=[
                {
                    "file_path": reference.file_path,
                    "line": reference.line,
                    "column": reference.column,
                    "kind": reference.kind.value,
                }
                for reference in references
            ],
            attributes={"symbol": qualified_name, "count": len(references)},
        )

    def _execute_call_hierarchy(self, request: ToolRequest) -> ToolResponse:
        qualified_name = self._require_symbol(request)
        direction = str(request.arguments.get("direction", "both"))

        result: dict[str, Any] = {}
        if direction in ("callers", "both"):
            result["callers"] = list(self._storage.callers_of(qualified_name))
        if direction in ("callees", "both"):
            result["callees"] = list(self._storage.callees_of(qualified_name))

        return ToolResponse(result=result, attributes={"symbol": qualified_name})

    def _execute_imports(self, request: ToolRequest) -> ToolResponse:
        path = self._require_path(request)
        support.ensure_indexed(
            self._storage,
            self._registry,
            path,
            max_file_size_bytes=self._max_file_size_bytes,
        )
        imports = self._storage.imports_for_file(str(path))

        return ToolResponse(
            result=[
                {
                    "imported_module": edge.imported_module,
                    "imported_symbol": edge.imported_symbol,
                    "line": edge.line,
                }
                for edge in imports
            ],
            attributes={"path": str(path), "count": len(imports)},
        )

    def _execute_dependencies(self, request: ToolRequest) -> ToolResponse:
        path = self._require_path(request)
        support.ensure_indexed(
            self._storage,
            self._registry,
            path,
            max_file_size_bytes=self._max_file_size_bytes,
        )
        imports = self._storage.imports_for_file(str(path))
        dependencies = support.deduplicated_dependencies(imports)

        return ToolResponse(
            result=list(dependencies),
            attributes={"path": str(path), "count": len(dependencies)},
        )

    def _execute_project_summary(self, request: ToolRequest) -> ToolResponse:
        root = str(request.arguments.get("root", "")).strip()

        if not root:
            raise InvalidCodingArgumentError(
                "request.arguments['root'] must be a non-empty string."
            )

        summary = support.build_project_summary(self._storage, root)

        return ToolResponse(
            result={
                "root": summary.root,
                "file_count": summary.file_count,
                "symbol_count": summary.symbol_count,
                "languages": dict(summary.languages),
            },
            attributes={"root": root},
        )

    def _execute_graph_query(self, request: ToolRequest) -> ToolResponse:
        qualified_name = self._require_symbol(request)
        direction = str(request.arguments.get("direction", "forward"))
        max_depth = int(request.arguments.get("max_depth", 3))

        traversal = self._storage.graph_query(
            qualified_name, direction=direction, max_depth=max_depth
        )

        return ToolResponse(
            result=_traversal_to_dict(traversal),
            attributes={"symbol": qualified_name},
        )

    def _execute_impact_analysis(self, request: ToolRequest) -> ToolResponse:
        qualified_name = self._require_symbol(request)
        max_depth = int(request.arguments.get("max_depth", 3))

        traversal = self._storage.graph_query(
            qualified_name, direction="reverse", max_depth=max_depth
        )

        return ToolResponse(
            result=_traversal_to_dict(traversal),
            attributes={"symbol": qualified_name},
        )

    # ------------------------------------------------------------------
    # Authoring / analysis operations
    # ------------------------------------------------------------------

    def _execute_rename_plan(self, request: ToolRequest) -> ToolResponse:
        qualified_name = self._require_symbol(request)
        new_name = str(request.arguments.get("new_name", "")).strip()

        if not new_name:
            raise InvalidCodingArgumentError(
                "request.arguments['new_name'] must be a non-empty string."
            )

        symbol, edits = support.build_rename_edits(
            self._storage, qualified_name, new_name
        )

        return ToolResponse(
            result={
                "symbol": qualified_name,
                "old_name": symbol.name,
                "new_name": new_name,
                "edits": edits,
            },
            attributes={"edit_count": len(edits)},
        )

    def _execute_refactor_plan(self, request: ToolRequest) -> ToolResponse:
        # This phase supports exactly one deterministic refactor kind:
        # "rename" (an alias of RENAME_PLAN). Additional refactor kinds
        # (extract function, move symbol, inline) are a documented
        # future increment -- see
        # docs/development/Tool_Guide.md
        # section 4.2/23.
        kind = str(request.arguments.get("kind", "rename"))

        if kind != "rename":
            raise InvalidCodingArgumentError(
                f"Refactor kind '{kind}' is not supported yet; only "
                "'rename' is implemented in this phase."
            )

        return self._execute_rename_plan(request)

    def _execute_patch_generate(self, request: ToolRequest) -> ToolResponse:
        raw_edits = request.arguments.get("edits")
        raw_originals = request.arguments.get("original_contents")

        if not isinstance(raw_edits, list) or not raw_edits:
            raise InvalidCodingArgumentError(
                "request.arguments['edits'] must be a non-empty list."
            )

        if not isinstance(raw_originals, dict):
            raise InvalidCodingArgumentError(
                "request.arguments['original_contents'] must be a "
                "mapping of file_path -> current file content."
            )

        from .model import TextEdit

        edits = tuple(
            TextEdit(
                file_path=str(edit["file_path"]),
                line=int(edit["line"]),
                column=int(edit.get("column", 0)),
                old_text=str(edit["old_text"]),
                new_text=str(edit["new_text"]),
            )
            for edit in raw_edits
        )

        proposal = render_patch(
            edits, original_contents={str(k): str(v) for k, v in raw_originals.items()}
        )

        return ToolResponse(
            result={
                "files": [
                    {
                        "file_path": file_patch.file_path,
                        "diff": file_patch.diff,
                        "new_content": file_patch.new_content,
                    }
                    for file_patch in proposal.files
                ]
            },
            attributes={"file_count": len(proposal.files)},
        )

    def _execute_document(self, request: ToolRequest) -> ToolResponse:
        qualified_name = self._require_symbol(request)
        symbol = self._storage.find_symbol(qualified_name)
        draft = support.build_document_draft(symbol)

        return ToolResponse(
            result={"symbol": qualified_name, "draft": draft},
            attributes={"symbol": qualified_name},
        )

    def _execute_format(self, request: ToolRequest) -> ToolResponse:
        return self._run_external_command(
            request, command_kind="formatter_command", label="Running formatter"
        )

    def _execute_lint(self, request: ToolRequest) -> ToolResponse:
        return self._run_external_command(
            request, command_kind="linter_command", label="Running linter"
        )

    def _execute_complexity(self, request: ToolRequest) -> ToolResponse:
        path = self._require_path(request)
        analyzer = self._registry.resolve(path)
        results = support.compute_complexity_for_path(
            path, analyzer.language_ids()[0] if analyzer.language_ids() else "text"
        )

        return ToolResponse(
            result=[
                {
                    "symbol": result.symbol_qualified_name,
                    "complexity": result.complexity,
                    "line_start": result.line_start,
                    "line_end": result.line_end,
                }
                for result in results
            ],
            attributes={"path": str(path), "count": len(results)},
        )

    def _execute_duplicates(self, request: ToolRequest) -> ToolResponse:
        raw_paths = request.arguments.get("paths")

        if not isinstance(raw_paths, list) or not raw_paths:
            raise InvalidCodingArgumentError(
                "request.arguments['paths'] must be a non-empty list "
                "of already-indexed file paths."
            )

        paths = [Path(str(item)) for item in raw_paths]
        threshold = float(request.arguments.get("similarity_threshold", 0.8))

        groups = support.compute_duplicates_for_paths(
            self._storage, paths, similarity_threshold=threshold
        )

        return ToolResponse(
            result=[
                {
                    "similarity": group.similarity,
                    "blocks": [
                        {
                            "symbol": block.symbol_qualified_name,
                            "file_path": block.file_path,
                            "line_start": block.line_start,
                            "line_end": block.line_end,
                        }
                        for block in group.blocks
                    ],
                }
                for group in groups
            ],
            attributes={"group_count": len(groups)},
        )

    def _execute_dead_code(self, request: ToolRequest) -> ToolResponse:
        candidates = support.compute_dead_code(self._storage)

        return ToolResponse(
            result=[
                {
                    "symbol": candidate.symbol_qualified_name,
                    "file_path": candidate.file_path,
                    "kind": candidate.kind.value,
                    "reason": candidate.reason,
                }
                for candidate in candidates
            ],
            attributes={"count": len(candidates)},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_external_command(
        self, request: ToolRequest, *, command_kind: str, label: str
    ) -> ToolResponse:
        path = self._require_path(request)
        analyzer = self._registry.resolve(path)
        command = getattr(analyzer, command_kind)(path)

        if command is None:
            raise CodingToolError(
                f"No {command_kind.replace('_command', '')} is configured "
                f"for '{path}'. Configure it under [coding.formatters]/"
                "[coding.linters]."
            )

        if self._tool_manager is None:
            raise CodingToolError(
                f"{label} requires a ToolManager reference to dispatch "
                "through the existing Shell Tool, but none was supplied."
            )

        self._progress.progress(message=f"{label} ({command[0]})...")

        response = self._tool_manager.execute(
            SHELL_EXECUTE_TOOL_ID,
            ToolRequest(
                arguments={
                    "command": list(command),
                    "cwd": str(path.parent),
                }
            ),
        )

        return ToolResponse(
            result=response.result,
            attributes={"path": str(path), "command": list(command)},
        )

    def _require_path(self, request: ToolRequest) -> Path:
        raw_path = request.arguments.get("path")

        if not isinstance(raw_path, str) or not raw_path.strip():
            raise InvalidCodingArgumentError(
                "request.arguments['path'] must be a non-empty string."
            )

        return Path(raw_path)

    def _require_symbol(self, request: ToolRequest) -> str:
        raw_symbol = request.arguments.get("symbol")

        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise InvalidCodingArgumentError(
                "request.arguments['symbol'] must be a non-empty "
                "qualified symbol name."
            )

        return raw_symbol


def _symbol_to_dict(symbol: Any) -> dict[str, Any]:
    return {
        "id": symbol.id,
        "kind": symbol.kind.value,
        "name": symbol.name,
        "qualified_name": symbol.qualified_name,
        "signature": symbol.signature,
        "docstring": symbol.docstring,
        "line_start": symbol.line_start,
        "line_end": symbol.line_end,
    }


def _traversal_to_dict(traversal: Any) -> dict[str, Any]:
    return {
        "root": traversal.root,
        "nodes": list(traversal.nodes),
        "edges": [
            {"source": edge.source, "target": edge.target, "kind": edge.kind}
            for edge in traversal.edges
        ],
        "truncated": traversal.truncated,
    }


_STARTED_MESSAGES: dict[CodingOperation, str] = {
    CodingOperation.PARSE: "Parsing source...",
    CodingOperation.SYMBOLS: "Building symbols...",
    CodingOperation.SEARCH: "Searching symbols...",
    CodingOperation.REFERENCES: "Searching references...",
    CodingOperation.CALL_HIERARCHY: "Building call hierarchy...",
    CodingOperation.IMPORTS: "Reading imports...",
    CodingOperation.DEPENDENCIES: "Building dependency graph...",
    CodingOperation.RENAME_PLAN: "Computing rename plan...",
    CodingOperation.REFACTOR_PLAN: "Computing refactor plan...",
    CodingOperation.PATCH_GENERATE: "Generating patch...",
    CodingOperation.DOCUMENT: "Generating documentation...",
    CodingOperation.FORMAT: "Running formatter...",
    CodingOperation.LINT: "Running linter...",
    CodingOperation.COMPLEXITY: "Computing complexity...",
    CodingOperation.DUPLICATES: "Searching for duplicates...",
    CodingOperation.DEAD_CODE: "Searching for dead code...",
    CodingOperation.PROJECT_SUMMARY: "Summarizing project...",
    CodingOperation.GRAPH_QUERY: "Building dependency graph...",
    CodingOperation.IMPACT_ANALYSIS: "Analyzing impact...",
}
