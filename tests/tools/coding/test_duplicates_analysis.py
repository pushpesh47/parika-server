"""
Unit tests for the token-shingling duplicate detector.
"""

from __future__ import annotations

from parika.tools.coding.analysis.duplicates import (
    find_duplicate_groups,
    jaccard_similarity,
    normalized_shingles,
)
from parika.tools.coding.model import Symbol, SymbolKind

FUNCTION_A = """
def add_numbers(first, second):
    total = first + second
    return total
"""

FUNCTION_B = """
def sum_numbers(alpha, beta):
    total = alpha + beta
    return total
"""

FUNCTION_C = """
def unrelated_logging_helper(message):
    print("LOG:", message)
    return None
"""


def _symbol(name: str) -> Symbol:
    return Symbol(
        id=f"file.py:1:function:{name}",
        file_path="file.py",
        kind=SymbolKind.FUNCTION,
        name=name,
        qualified_name=f"file.{name}",
        line_start=1,
        line_end=4,
    )


def test_identical_sources_have_similarity_one() -> None:
    shingles = normalized_shingles(FUNCTION_A, shingle_size=3)
    assert jaccard_similarity(shingles, shingles) == 1.0


def test_renamed_identifiers_still_match_closely() -> None:
    shingles_a = normalized_shingles(FUNCTION_A, shingle_size=3)
    shingles_b = normalized_shingles(FUNCTION_B, shingle_size=3)

    assert jaccard_similarity(shingles_a, shingles_b) >= 0.8


def test_find_duplicate_groups_groups_renamed_copy() -> None:
    groups = find_duplicate_groups(
        [
            (_symbol("add_numbers"), FUNCTION_A),
            (_symbol("sum_numbers"), FUNCTION_B),
            (_symbol("unrelated_logging_helper"), FUNCTION_C),
        ],
        similarity_threshold=0.7,
        shingle_size=3,
        minimum_tokens=5,
    )

    assert len(groups) == 1
    names = {block.symbol_qualified_name for block in groups[0].blocks}
    assert names == {"file.add_numbers", "file.sum_numbers"}


def test_short_symbols_are_excluded_by_minimum_tokens() -> None:
    groups = find_duplicate_groups(
        [
            (_symbol("a"), "def a(): return 1\n"),
            (_symbol("b"), "def b(): return 1\n"),
        ],
        minimum_tokens=50,
    )

    assert groups == ()
