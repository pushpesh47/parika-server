"""
PARIKA Coding Tool - Dead Code Detection

Thin, read-only wrapper over `CodingIndexStorage.dead_code_candidates()`
-- a symbol with zero non-definition references and not matching a
configured entry-point allow-list. Reported with its evidence, never
auto-deleted -- the same "returns candidates, caller decides" shape as
`MemoryManager.consolidation_candidates()`.
"""

from __future__ import annotations

from parika.tools.coding.model import DeadCodeCandidate
from parika.tools.coding.storage import CodingIndexStorage


def find_dead_code(
    storage: CodingIndexStorage,
    *,
    entry_point_prefixes: tuple[str, ...] = ("__main__", "test_"),
) -> tuple[DeadCodeCandidate, ...]:
    symbols = storage.dead_code_candidates(
        entry_point_prefixes=entry_point_prefixes
    )

    return tuple(
        DeadCodeCandidate(
            symbol_qualified_name=symbol.qualified_name,
            file_path=symbol.file_path,
            kind=symbol.kind,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            reason="No references or call sites were found in the index.",
        )
        for symbol in symbols
    )
