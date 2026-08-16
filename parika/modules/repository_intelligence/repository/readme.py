"""
PARIKA Repository Intelligence - README Discovery

Locates a repository's README file so it can be registered as its own
child `KnowledgeSource(kind=DOCUMENTATION)` and indexed by the
existing, unmodified `DocumentKnowledgeEngine` -- the entire "README
understanding" requirement, satisfied with zero new document-parsing
code. See
docs/development/Module_Guide.md section
6.1.
"""

from __future__ import annotations

from pathlib import Path

_README_NAMES: tuple[str, ...] = (
    "README.md",
    "readme.md",
    "Readme.md",
    "README.rst",
    "README.txt",
    "README",
)


def find_readme(repository_root: Path) -> Path | None:
    """
    Return the first README-shaped file found directly under
    `repository_root`, or `None` if none exists.
    """

    for name in _README_NAMES:
        candidate = repository_root / name

        if candidate.is_file():
            return candidate

    return None
