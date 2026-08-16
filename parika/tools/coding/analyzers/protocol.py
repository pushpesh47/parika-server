"""
PARIKA Coding Tool - Language Analyzer Protocol

Defines the pluggable extension point every language implementation
satisfies. Adding a new language is: write one new `LanguageAnalyzer`
implementation, add one entry to `LanguageAnalyzerRegistry`'s default
tuple -- zero changes to `ToolManager`, `Planner`, `CapabilityExecutor`,
or any other analyzer. The same "Protocol + registry + default
implementations" shape already used by `ScoringRule` and
`KnowledgeEngine` elsewhere in this codebase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from parika.tools.coding.model import ParsedFile


@runtime_checkable
class LanguageAnalyzer(Protocol):
    """
    One implementation per language or language family.

    A `LanguageAnalyzer` is a pure function object: `parse()` performs
    no I/O and no side effects, and never mutates PARIKA state -- the
    Coding Tool is never a filesystem tool (see
    docs/development/Tool_Guide.md
    section 4.1).
    """

    def language_ids(self) -> tuple[str, ...]:
        """
        Return every language identifier this analyzer handles (e.g.
        ``("python",)``).
        """
        ...

    def supports(self, path: Path) -> bool:
        """
        Determine whether this analyzer can parse `path`.
        """
        ...

    def parse(self, path: Path, text: str) -> ParsedFile:
        """
        Parse `text` (already read from `path` by the caller) into an
        immutable `ParsedFile`.

        Raises:
            LanguageAnalyzerUnavailableError:
                If this analyzer's optional backend dependency is not
                installed.
        """
        ...

    def formatter_command(self, path: Path) -> tuple[str, ...] | None:
        """
        Return the argv command used to format `path`, or `None` when
        no formatter is configured for this language. Executed by the
        caller through the existing Shell Tool -- this analyzer never
        spawns a process itself.
        """
        ...

    def linter_command(self, path: Path) -> tuple[str, ...] | None:
        """
        Return the argv command used to lint `path`, or `None` when no
        linter is configured for this language. Executed by the caller
        through the existing Shell Tool.
        """
        ...
