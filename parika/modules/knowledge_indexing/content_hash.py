"""
PARIKA Knowledge Indexing - Content Hashing (deprecated re-export)

This module's implementation was relocated, verbatim, to
`parika.modules._shared.content_hash` so that both `knowledge_indexing`
and `repository_intelligence` can import it identically without either
depending on the other's Module package (see
docs/development/Module_Guide.md section
5.6). This module now only re-exports the two functions, preserving
backward compatibility for any existing `from
parika.modules.knowledge_indexing.content_hash import ...` statement.

Prefer importing from `parika.modules._shared.content_hash` directly
in new code.
"""

from __future__ import annotations

from parika.modules._shared.content_hash import compute_content_hash, iter_files

__all__ = ["compute_content_hash", "iter_files"]
