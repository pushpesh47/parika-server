"""
PARIKA Coding Tool - Language Analyzers.

One `LanguageAnalyzer` implementation per language or language family,
resolved through `LanguageAnalyzerRegistry`.
"""

from __future__ import annotations

from .generic_text import GenericTextAnalyzer
from .protocol import LanguageAnalyzer
from .python_ast import PythonAstAnalyzer
from .registry import (
    DEFAULT_TREE_SITTER_LANGUAGE_IDS,
    LanguageAnalyzerRegistry,
    default_analyzers,
)
from .tree_sitter_analyzer import TreeSitterAnalyzer

__all__ = [
    "DEFAULT_TREE_SITTER_LANGUAGE_IDS",
    "GenericTextAnalyzer",
    "LanguageAnalyzer",
    "LanguageAnalyzerRegistry",
    "PythonAstAnalyzer",
    "TreeSitterAnalyzer",
    "default_analyzers",
]
