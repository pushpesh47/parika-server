"""
PARIKA Coding Tool - Model

Immutable value objects shared across the Coding Tool's analyzers,
storage, and driver. None of these types contain behavior beyond
validation/normalization, matching every other PARIKA model class
(`Tool`, `Goal`, `KnowledgeSource`, ...).

See docs/development/Tool_Guide.md
section 4 for the full design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class SymbolKind(StrEnum):
    """
    The kind of a source-code symbol.
    """

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"


class ReferenceKind(StrEnum):
    """
    The kind of a reference to a symbol.
    """

    READ = "read"
    WRITE = "write"
    CALL = "call"
    IMPORT = "import"


class AnnotationKind(StrEnum):
    """
    The kind of an extracted source annotation.
    """

    TODO = "todo"
    FIXME = "fixme"
    COMMENT = "comment"
    DOCSTRING = "docstring"


@dataclass(frozen=True, slots=True, kw_only=True)
class Symbol:
    """
    A single indexed symbol (module, class, function, method, or
    variable) extracted from one file.
    """

    id: str
    file_path: str
    kind: SymbolKind
    name: str
    qualified_name: str
    signature: str | None = None
    docstring: str | None = None
    line_start: int = 0
    line_end: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportEdge:
    """
    A single import statement extracted from one file.
    """

    file_path: str
    imported_module: str
    imported_symbol: str | None = None
    line: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceEdge:
    """
    A single reference (read/write/call/import) to a symbol, found
    while parsing a file.

    `symbol_qualified_name` identifies the referenced symbol by name
    rather than by storage id, since a `LanguageAnalyzer.parse()` call
    is a pure function with no knowledge of `CodingIndexStorage`'s
    assigned identifiers; `CodingIndexStorage.upsert_file()` resolves
    the final `symbol_id` when persisting.
    """

    file_path: str
    symbol_qualified_name: str
    kind: ReferenceKind
    line: int = 0
    column: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class CallEdge:
    """
    A single "caller calls callee" relationship found while parsing a
    file. Both sides are identified by qualified name, resolved to
    storage ids by `CodingIndexStorage.upsert_file()`.
    """

    caller_qualified_name: str
    callee_qualified_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Annotation:
    """
    A single TODO/FIXME/comment/docstring found while parsing a file.
    """

    file_path: str
    kind: AnnotationKind
    text: str
    line: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostic:
    """
    A single parse-time diagnostic (e.g. a syntax error) reported by a
    `LanguageAnalyzer`. Never a lint/format finding -- see
    `coding.lint`'s own `LintFinding` for that.
    """

    message: str
    line: int = 0
    column: int = 0
    severity: str = "error"


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedFile:
    """
    The immutable result of parsing a single file with one
    `LanguageAnalyzer`. A pure value object: no I/O, no side effects.
    """

    file_path: str
    language: str
    content_hash: str
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[ImportEdge, ...] = ()
    references: tuple[ReferenceEdge, ...] = ()
    call_edges: tuple[CallEdge, ...] = ()
    annotations: tuple[Annotation, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class TextEdit:
    """
    A single, precise text replacement within one file.
    """

    file_path: str
    line: int
    column: int
    old_text: str
    new_text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RenamePlan:
    """
    A read-only, computed rename proposal. Never applied by the
    Coding Tool itself -- see `coding.patch_generate` and
    docs/development/Tool_Guide.md
    section 4.7.
    """

    symbol_qualified_name: str
    old_name: str
    new_name: str
    edits: tuple[TextEdit, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class FilePatch:
    """
    A single file's rendered unified diff plus its full new content.

    `new_content` is what a caller (typically the Coding Agent) passes
    directly to `filesystem.write` -- the Coding Tool never applies a
    diff itself, and the Filesystem Tool never parses one.
    """

    file_path: str
    diff: str
    new_content: str


@dataclass(frozen=True, slots=True, kw_only=True)
class PatchProposal:
    """
    A read-only, computed set of per-file patches.
    """

    files: tuple[FilePatch, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ComplexityResult:
    """
    A single function/method's cyclomatic-complexity-style metric.
    """

    symbol_qualified_name: str
    file_path: str
    complexity: int
    line_start: int = 0
    line_end: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class DuplicateBlock:
    """
    One member of a detected near-duplicate group.
    """

    symbol_qualified_name: str
    file_path: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DuplicateGroup:
    """
    A group of near-duplicate code blocks, detected by normalized
    token-shingling.
    """

    blocks: tuple[DuplicateBlock, ...] = ()
    similarity: float = 1.0


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadCodeCandidate:
    """
    A symbol with zero non-definition references and not matching a
    configured entry-point allow-list. Reported with its evidence,
    never auto-deleted.
    """

    symbol_qualified_name: str
    file_path: str
    kind: SymbolKind
    line_start: int = 0
    line_end: int = 0
    reason: str = "No references found."


@dataclass(frozen=True, slots=True, kw_only=True)
class LintFinding:
    """
    One normalized diagnostic reported by an external formatter/linter
    binary run through the Shell Tool (see `coding.lint`).
    """

    file_path: str
    message: str
    line: int = 0
    column: int = 0
    severity: str = "warning"
    rule: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphEdge:
    """
    A single directed edge in a call/import/symbol/module/package
    graph traversal result.
    """

    source: str
    target: str
    kind: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphTraversalResult:
    """
    The bounded-depth traversal result of `coding.graph_query`/
    `coding.impact_analysis`.
    """

    root: str
    nodes: tuple[str, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectSummaryResult:
    """
    A deterministic, non-LLM structural summary of a repository or
    package -- file/symbol counts, detected languages. Never a
    natural-language narrative (see
    docs/development/Tool_Guide.md
    section 6.4).
    """

    root: str
    file_count: int = 0
    symbol_count: int = 0
    languages: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "languages", MappingProxyType(dict(self.languages))
        )
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )
