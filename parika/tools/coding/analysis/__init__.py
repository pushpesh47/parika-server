"""
PARIKA Coding Tool - Analysis.

Deterministic, read-only analysis passes: complexity, near-duplicate
detection, and dead-code candidate detection.
"""

from __future__ import annotations

from .complexity import compute_python_complexity
from .dead_code import find_dead_code
from .duplicates import find_duplicate_groups, jaccard_similarity, normalized_shingles

__all__ = [
    "compute_python_complexity",
    "find_dead_code",
    "find_duplicate_groups",
    "jaccard_similarity",
    "normalized_shingles",
]
