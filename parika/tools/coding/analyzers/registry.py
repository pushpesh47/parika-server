"""
PARIKA Coding Tool - Language Analyzer Registry

Resolves a file path to the first `LanguageAnalyzer` whose `supports()`
returns `True`, falling back to `GenericTextAnalyzer` when none
matches. See
docs/development/Tool_Guide.md section
4.3.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from .generic_text import GenericTextAnalyzer
from .protocol import LanguageAnalyzer
from .python_ast import PythonAstAnalyzer
from .tree_sitter_analyzer import TreeSitterAnalyzer, _EXTENSION_TO_LANGUAGE

DEFAULT_TREE_SITTER_LANGUAGE_IDS: tuple[str, ...] = tuple(
    sorted(set(_EXTENSION_TO_LANGUAGE.values()))
)


def default_analyzers(
    *,
    formatters: Mapping[str, tuple[str, ...]] | None = None,
    linters: Mapping[str, tuple[str, ...]] | None = None,
    tree_sitter_enabled: bool = True,
) -> tuple[LanguageAnalyzer, ...]:
    """
    Build the default analyzer tuple: `PythonAstAnalyzer` first
    (always available), one `TreeSitterAnalyzer` per supported
    language (each independently reporting itself unavailable when
    the optional dependency group is absent, or when
    `tree_sitter_enabled` is `False`), and `GenericTextAnalyzer` last
    as the fallback of last resort.
    """

    analyzers: list[LanguageAnalyzer] = [
        PythonAstAnalyzer(formatters=formatters, linters=linters)
    ]

    if tree_sitter_enabled:
        analyzers.extend(
            TreeSitterAnalyzer(
                language_id, formatters=formatters, linters=linters
            )
            for language_id in DEFAULT_TREE_SITTER_LANGUAGE_IDS
        )

    analyzers.append(GenericTextAnalyzer(formatters=formatters, linters=linters))

    return tuple(analyzers)


class LanguageAnalyzerRegistry:
    """
    Resolves a `Path` to its `LanguageAnalyzer`, in registration order.
    """

    def __init__(self, analyzers: Sequence[LanguageAnalyzer] | None = None) -> None:
        """
        Initialize the registry.

        Args:
            analyzers:
                Explicit analyzer sequence, tried in order. Defaults
                to `default_analyzers()` when omitted.
        """

        self._analyzers: tuple[LanguageAnalyzer, ...] = (
            tuple(analyzers) if analyzers is not None else default_analyzers()
        )

    def resolve(self, path: Path) -> LanguageAnalyzer:
        """
        Resolve the analyzer for `path`.

        Always returns an analyzer -- `GenericTextAnalyzer` (or the
        last registered analyzer whose `supports()` returns `True`
        for everything) is guaranteed to match when nothing more
        specific does.
        """

        for analyzer in self._analyzers:
            if analyzer.supports(path):
                return analyzer

        # Unreachable when `default_analyzers()` was used (its last
        # entry matches everything), but kept as a defensive fallback
        # for a caller-supplied analyzer sequence with no catch-all.
        return GenericTextAnalyzer()

    def all(self) -> tuple[LanguageAnalyzer, ...]:
        """
        Return every registered analyzer, in resolution order.
        """

        return self._analyzers
