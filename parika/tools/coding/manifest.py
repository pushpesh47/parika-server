"""
PARIKA Coding Tool - Manifest

Defines the static Tool metadata describing every Coding Tool
operation, following the exact "one Tool per Capability" shape
`Tool_Guide.md` section 21 establishes -- the Filesystem/Shell Tools
are its direct templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from parika.core.tool_manager.tool import Tool

CODING_TOOL_VERSION = "1.0.0"


class CodingOperation(StrEnum):
    """
    Every operation the Coding Tool implements, one per registered
    Capability.
    """

    PARSE = "parse"
    SYMBOLS = "symbols"
    SEARCH = "search"
    REFERENCES = "references"
    CALL_HIERARCHY = "call_hierarchy"
    IMPORTS = "imports"
    DEPENDENCIES = "dependencies"
    RENAME_PLAN = "rename_plan"
    REFACTOR_PLAN = "refactor_plan"
    PATCH_GENERATE = "patch_generate"
    DOCUMENT = "document"
    FORMAT = "format"
    LINT = "lint"
    COMPLEXITY = "complexity"
    DUPLICATES = "duplicates"
    DEAD_CODE = "dead_code"
    PROJECT_SUMMARY = "project_summary"
    GRAPH_QUERY = "graph_query"
    IMPACT_ANALYSIS = "impact_analysis"


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingOperationSpec:
    """
    Everything needed to register one Coding Tool operation as its
    own Tool + Capability pair.
    """

    operation: CodingOperation
    capability_id: str
    tool_id: str
    name: str
    description: str


CODING_OPERATIONS: tuple[CodingOperationSpec, ...] = (
    CodingOperationSpec(
        operation=CodingOperation.PARSE,
        capability_id="coding.parse",
        tool_id="tool.coding_parse",
        name="Coding Parse",
        description="Parses one file into symbols, imports, and diagnostics.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.SYMBOLS,
        capability_id="coding.symbols",
        tool_id="tool.coding_symbols",
        name="Coding Symbols",
        description="Lists indexed symbols for a file.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.SEARCH,
        capability_id="coding.search",
        tool_id="tool.coding_search",
        name="Coding Search",
        description="Searches indexed symbols by name/signature/docstring.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.REFERENCES,
        capability_id="coding.references",
        tool_id="tool.coding_references",
        name="Coding References",
        description="Returns every reference to a given symbol.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.CALL_HIERARCHY,
        capability_id="coding.call_hierarchy",
        tool_id="tool.coding_call_hierarchy",
        name="Coding Call Hierarchy",
        description="Returns callers and/or callees of a symbol.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.IMPORTS,
        capability_id="coding.imports",
        tool_id="tool.coding_imports",
        name="Coding Imports",
        description="Lists a file's imports.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.DEPENDENCIES,
        capability_id="coding.dependencies",
        tool_id="tool.coding_dependencies",
        name="Coding Dependencies",
        description="Resolves a file's deduplicated import dependency set.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.RENAME_PLAN,
        capability_id="coding.rename_plan",
        tool_id="tool.coding_rename_plan",
        name="Coding Rename Plan",
        description="Computes every edit a symbol rename must apply.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.REFACTOR_PLAN,
        capability_id="coding.refactor_plan",
        tool_id="tool.coding_refactor_plan",
        name="Coding Refactor Plan",
        description="Computes a structural refactor's affected locations.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.PATCH_GENERATE,
        capability_id="coding.patch_generate",
        tool_id="tool.coding_patch_generate",
        name="Coding Patch Generate",
        description="Renders an edit list into a unified diff, never applying it.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.DOCUMENT,
        capability_id="coding.document",
        tool_id="tool.coding_document",
        name="Coding Document",
        description="Generates a deterministic docstring draft for a symbol.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.FORMAT,
        capability_id="coding.format",
        tool_id="tool.coding_format",
        name="Coding Format",
        description="Runs the configured formatter for a file via the Shell Tool.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.LINT,
        capability_id="coding.lint",
        tool_id="tool.coding_lint",
        name="Coding Lint",
        description="Runs the configured linter for a file via the Shell Tool.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.COMPLEXITY,
        capability_id="coding.complexity",
        tool_id="tool.coding_complexity",
        name="Coding Complexity",
        description="Computes a cyclomatic-complexity-style metric per symbol.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.DUPLICATES,
        capability_id="coding.duplicates",
        tool_id="tool.coding_duplicates",
        name="Coding Duplicates",
        description="Detects near-duplicate code blocks by token shingling.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.DEAD_CODE,
        capability_id="coding.dead_code",
        tool_id="tool.coding_dead_code",
        name="Coding Dead Code",
        description="Reports unreferenced-symbol dead-code candidates.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.PROJECT_SUMMARY,
        capability_id="coding.project_summary",
        tool_id="tool.coding_project_summary",
        name="Coding Project Summary",
        description="Deterministic structural summary of indexed files/symbols.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.GRAPH_QUERY,
        capability_id="coding.graph_query",
        tool_id="tool.coding_graph_query",
        name="Coding Graph Query",
        description="Bounded-depth traversal of the call graph.",
    ),
    CodingOperationSpec(
        operation=CodingOperation.IMPACT_ANALYSIS,
        capability_id="coding.impact_analysis",
        tool_id="tool.coding_impact_analysis",
        name="Coding Impact Analysis",
        description="Reverse call-graph traversal: what depends on this symbol.",
    ),
)
"""
Every Coding Tool operation PARIKA implements, in the order the
`coding` Module registers them. Adding a future operation means
appending one entry here and one handler in `driver.py` -- no other
module needs to change.
"""


def create_coding_tool(spec: CodingOperationSpec) -> Tool:
    """
    Build the immutable Tool descriptor for one Coding Tool operation.
    """

    return Tool(
        id=spec.tool_id,
        name=spec.name,
        version=CODING_TOOL_VERSION,
        description=spec.description,
        capabilities=(spec.capability_id,),
    )
