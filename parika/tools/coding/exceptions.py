"""
PARIKA Coding Tool - Exceptions

Dedicated exception hierarchy for the Coding Tool. Uniformly wrapped
into `ToolExecutionError` by `ToolManager.execute()`, exactly like
every existing Tool's own exception hierarchy.
"""

from __future__ import annotations


class CodingToolError(Exception):
    """
    Base exception for every Coding Tool failure.
    """


class InvalidCodingArgumentError(CodingToolError):
    """
    Raised when a required argument is missing or invalid.
    """


class UnsupportedLanguageError(CodingToolError):
    """
    Raised when the resolved `LanguageAnalyzer` for a path cannot
    satisfy the requested operation (e.g. `call_hierarchy` on a file
    only the generic fallback analyzer supports).
    """


class LanguageAnalyzerUnavailableError(CodingToolError):
    """
    Raised when a Tree-sitter-backed analyzer is requested but the
    optional `tree-sitter`/`tree-sitter-language-pack` dependency
    group is not installed.
    """


class CodingIndexNotFoundError(CodingToolError):
    """
    Raised when a query targets a file/symbol never indexed.
    """


class PatchGenerationError(CodingToolError):
    """
    Raised when a patch cannot be rendered from the supplied edits.
    """
