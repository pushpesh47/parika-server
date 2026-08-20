"""
PARIKA Coding Tool package.

Provides semantic understanding of source code -- parsing, symbol
indexing, search, cross-reference analysis, call hierarchy, import/
dependency analysis, rename/refactor planning, patch generation,
documentation generation, formatting, static analysis, complexity,
duplicate/dead-code detection. Explicitly NOT a filesystem tool: every
operation is read-only with respect to source files; mutation is
always performed by the existing Filesystem Tool, invoked by the
caller (typically the Coding Agent).

See docs/development/Tool_Guide.md
section 4 for the full design.
"""

from __future__ import annotations

from .config import CodingToolConfig, load_coding_config
from .driver import CodingToolDriver
from .exceptions import (
    CodingIndexNotFoundError,
    CodingToolError,
    InvalidCodingArgumentError,
    LanguageAnalyzerUnavailableError,
    PatchGenerationError,
    UnsupportedLanguageError,
)
from .manifest import (
    CODING_OPERATIONS,
    CODING_TOOL_VERSION,
    CodingOperation,
    CodingOperationSpec,
    create_coding_tool,
)
from .postgresql_storage import PostgreSQLCodingIndexStorage

__all__ = [
    "CODING_OPERATIONS",
    "CODING_TOOL_VERSION",
    "CodingIndexNotFoundError",
    "CodingIndexStorage",
    "CodingOperation",
    "CodingOperationSpec",
    "CodingToolConfig",
    "CodingToolDriver",
    "CodingToolError",
    "InvalidCodingArgumentError",
    "LanguageAnalyzerUnavailableError",
    "PatchGenerationError",
    "UnsupportedLanguageError",
    "PostgreSQLCodingIndexStorage",
    "create_coding_tool",
    "load_coding_config",
]
