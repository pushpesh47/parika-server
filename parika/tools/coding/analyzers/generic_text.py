"""
PARIKA Coding Tool - Generic Text Analyzer

Stdlib-only, regex/line-based fallback `LanguageAnalyzer` used for any
file no dedicated analyzer supports yet. Always available, matching
the `universal-ctags`-style "at least something" symbol extraction
researched for this design (see
docs/development/Tool_Guide.md section
23) -- never a crash, never a hard dependency on Tree-sitter.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from parika.tools.coding.model import Annotation, AnnotationKind, ParsedFile

from .base import ConfigurableCommandsMixin

_MARKER_PATTERN = re.compile(
    r"(?://|#|--|;)\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)", re.IGNORECASE
)
_MARKER_KIND = {
    "TODO": AnnotationKind.TODO,
    "FIXME": AnnotationKind.FIXME,
    "HACK": AnnotationKind.FIXME,
    "XXX": AnnotationKind.FIXME,
}


class GenericTextAnalyzer(ConfigurableCommandsMixin):
    """
    Always-available fallback analyzer.

    Extracts only TODO/FIXME-style annotations by scanning for common
    single-line comment markers (``//``, ``#``, ``--``, ``;``). Does
    not extract symbols, imports, or references -- callers should
    expect `coding.symbols`/`coding.references`/`coding.call_hierarchy`
    to report `UnsupportedLanguageError` for a file resolved to this
    analyzer, per
    docs/development/Tool_Guide.md
    section 4.3.
    """

    def language_ids(self) -> tuple[str, ...]:
        return ("text",)

    def supports(self, path: Path) -> bool:
        # Deliberately matches everything -- the registry's fallback
        # of last resort.
        return True

    def parse(self, path: Path, text: str) -> ParsedFile:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        annotations: list[Annotation] = []

        for line_number, line in enumerate(text.splitlines(), start=1):
            match = _MARKER_PATTERN.search(line)

            if match:
                keyword = match.group(1).upper()
                annotations.append(
                    Annotation(
                        file_path=str(path),
                        kind=_MARKER_KIND.get(keyword, AnnotationKind.COMMENT),
                        text=match.group(2).strip() or keyword,
                        line=line_number,
                    )
                )

        return ParsedFile(
            file_path=str(path),
            language="text",
            content_hash=content_hash,
            annotations=tuple(annotations),
        )
