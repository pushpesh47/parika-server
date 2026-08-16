"""
PARIKA Coding Tool - Analyzer Base

Small, shared, formatter/linter-command lookup helper reused by every
`LanguageAnalyzer` implementation, so `coding.format`/`coding.lint`'s
"delegate to an already-installed external tool via the Shell Tool"
behavior (see
docs/development/Tool_Guide.md section
4.9) is implemented exactly once, not duplicated per analyzer.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


class ConfigurableCommandsMixin:
    """
    Resolves a language's formatter/linter argv command from an
    injected, read-only mapping (`[coding.formatters]`/
    `[coding.linters]`, see `config.py`).
    """

    def __init__(
        self,
        *,
        formatters: Mapping[str, tuple[str, ...]] | None = None,
        linters: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._formatters = dict(formatters or {})
        self._linters = dict(linters or {})

    def formatter_command(self, path: Path) -> tuple[str, ...] | None:
        for language_id in self.language_ids():  # type: ignore[attr-defined]
            command = self._formatters.get(language_id)

            if command:
                return (*command, str(path))

        return None

    def linter_command(self, path: Path) -> tuple[str, ...] | None:
        for language_id in self.language_ids():  # type: ignore[attr-defined]
            command = self._linters.get(language_id)

            if command:
                return (*command, str(path))

        return None
