"""
PARIKA Modules - Content Hashing

Stdlib-only content hashing shared by every Module that performs
incremental, content-hash-gated indexing -- originally implemented
inside `knowledge_indexing` and relocated here, verbatim, so it can be
imported identically by both `knowledge_indexing` and
`repository_intelligence` without either depending on the other's
Module package (see
docs/development/Module_Guide.md section
5.6). Supports `KnowledgeManager.index_incremental()` (see
docs/architecture/Intelligence_Foundation_Design.md section 5.4).

`parika.modules.knowledge_indexing.content_hash` re-exports this
module's two functions for backward compatibility with any existing
import of the old location.
"""

from __future__ import annotations

import hashlib

from pathlib import Path


def compute_content_hash(paths: list[Path]) -> str:
    """
    Compute a stable content hash over a set of files.

    Hashes each file's relative-path-independent content and mtime,
    combined in sorted-by-path order so the result is deterministic
    regardless of filesystem iteration order.
    """

    digest = hashlib.sha256()

    for path in sorted(paths):
        try:
            stat = path.stat()
            digest.update(str(path).encode("utf-8"))
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
        except OSError:
            continue

    return digest.hexdigest()


def iter_files(root: Path, *, suffixes: tuple[str, ...] | None = None) -> list[Path]:
    """
    Return every file under `root` (or `root` itself if it is a file),
    optionally filtered by suffix.
    """

    if root.is_file():
        return [root] if suffixes is None or root.suffix in suffixes else []

    if not root.is_dir():
        return []

    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and (suffixes is None or path.suffix in suffixes)
    ]
