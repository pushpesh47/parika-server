"""
PARIKA Coding Tool - Duplicate Detection

Stdlib-only, token-shingling near-duplicate code block detection.
Identifiers are normalized to a positional placeholder so a renamed
copy of the same block still matches -- the same category of
technique PMD's CPD/`jscpd` use (researched, not copied -- see
docs/development/Tool_Guide.md section
4.10/23).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from parika.tools.coding.model import DuplicateBlock, DuplicateGroup, Symbol

_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[^\sA-Za-z0-9_]")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_KEYWORDS = frozenset(
    {
        "def", "class", "if", "elif", "else", "for", "while", "try",
        "except", "finally", "with", "return", "yield", "import",
        "from", "as", "pass", "break", "continue", "raise", "and",
        "or", "not", "in", "is", "None", "True", "False", "self",
        "function", "var", "let", "const", "public", "private",
    }
)


def normalized_shingles(source: str, *, shingle_size: int = 5) -> frozenset[str]:
    """
    Tokenize `source`, replace every non-keyword identifier with a
    positional placeholder, and return the set of `shingle_size`-token
    shingles.
    """

    tokens = _TOKEN_PATTERN.findall(source)
    normalized: list[str] = []

    for index, token in enumerate(tokens):
        if _IDENTIFIER_PATTERN.match(token) and token not in _KEYWORDS:
            normalized.append("ID")
        else:
            normalized.append(token)

    if len(normalized) < shingle_size:
        return frozenset({" ".join(normalized)}) if normalized else frozenset()

    return frozenset(
        " ".join(normalized[index : index + shingle_size])
        for index in range(len(normalized) - shingle_size + 1)
    )


def jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0

    if not left or not right:
        return 0.0

    intersection = len(left & right)
    union = len(left | right)

    return intersection / union if union else 0.0


def find_duplicate_groups(
    symbols_with_source: Sequence[tuple[Symbol, str]],
    *,
    similarity_threshold: float = 0.8,
    shingle_size: int = 5,
    minimum_tokens: int = 20,
) -> tuple[DuplicateGroup, ...]:
    """
    Group near-duplicate symbols by shingle-set Jaccard similarity.

    Args:
        symbols_with_source:
            Each candidate symbol paired with its own source text
            (already read/sliced by the caller -- this function
            performs no I/O).

        similarity_threshold:
            Minimum Jaccard similarity for two symbols to be grouped.

        minimum_tokens:
            Symbols whose source tokenizes to fewer than this many
            tokens are skipped -- trivial one-line functions would
            otherwise dominate the result with meaningless matches.
    """

    candidates = [
        (symbol, normalized_shingles(source, shingle_size=shingle_size))
        for symbol, source in symbols_with_source
        if len(_TOKEN_PATTERN.findall(source)) >= minimum_tokens
    ]

    groups: list[list[tuple[Symbol, frozenset[str]]]] = []

    for symbol, shingles in candidates:
        placed = False

        for group in groups:
            if jaccard_similarity(shingles, group[0][1]) >= similarity_threshold:
                group.append((symbol, shingles))
                placed = True
                break

        if not placed:
            groups.append([(symbol, shingles)])

    results: list[DuplicateGroup] = []

    for group in groups:
        if len(group) < 2:
            continue

        similarity = min(
            jaccard_similarity(group[0][1], other[1]) for other in group[1:]
        )
        results.append(
            DuplicateGroup(
                blocks=tuple(
                    DuplicateBlock(
                        symbol_qualified_name=symbol.qualified_name,
                        file_path=symbol.file_path,
                        line_start=symbol.line_start,
                        line_end=symbol.line_end,
                    )
                    for symbol, _ in group
                ),
                similarity=similarity,
            )
        )

    return tuple(results)
