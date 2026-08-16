"""
PARIKA Memory Export / Import

JSON-based interchange format for permanent memory, used by
MemoryManager.export()/import_memories() and doubling as the portable
backend PARIKA's storage abstraction promises (see
docs/architecture/Intelligence_Foundation_Design.md and the storage
abstraction requirement in the Phase 1 Completion Specification,
section 19): every Memory can always be losslessly round-tripped
through this plain-JSON representation regardless of which concrete
MemoryStorage backend (SQLite today; a future vector-backed
implementation) produced it.
"""

from __future__ import annotations

import json

from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from parika.core.memory_manager.exceptions import MemoryPersistenceError
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import MemoryImportance
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.memory_manager.memory_scope import MemoryScope
from parika.core.memory_manager.storage import MemoryStorage

_EXPORT_FORMAT_VERSION: int = 1


def memory_to_json_dict(memory: Memory) -> dict[str, object]:
    """Convert one Memory into a plain, JSON-serializable dict."""

    return {
        "memory_id": memory.memory_id,
        "kind": memory.kind.value,
        "origin": memory.origin.value,
        "content": memory.content,
        "created_at": memory.created_at.isoformat(),
        "updated_at": memory.updated_at.isoformat(),
        "tags": sorted(memory.tags),
        "metadata": dict(memory.metadata),
        "scope": memory.scope.value,
        "session_id": memory.session_id,
        "importance_score": memory.importance_score,
        "access_count": memory.access_count,
        "last_accessed_at": (
            memory.last_accessed_at.isoformat()
            if memory.last_accessed_at is not None
            else None
        ),
        "decay_at": memory.decay_at.isoformat() if memory.decay_at is not None else None,
        "category": memory.category.value,
        "importance": memory.importance.value,
        "confidence": memory.confidence,
    }


def memory_from_json_dict(data: dict[str, Any]) -> Memory:
    """Convert one plain JSON dict back into a Memory."""

    return Memory(
        memory_id=str(data["memory_id"]),
        kind=MemoryKind(data["kind"]),
        origin=MemoryOrigin(data["origin"]),
        content=str(data["content"]),
        created_at=datetime.fromisoformat(str(data["created_at"])),
        updated_at=datetime.fromisoformat(str(data["updated_at"])),
        tags=frozenset(str(tag) for tag in data.get("tags", [])),
        metadata=MappingProxyType(dict(data.get("metadata", {}))),
        scope=MemoryScope(data["scope"]),
        session_id=data.get("session_id"),
        importance_score=float(data["importance_score"]),
        access_count=int(data.get("access_count", 0)),
        last_accessed_at=(
            datetime.fromisoformat(str(data["last_accessed_at"]))
            if data.get("last_accessed_at") is not None
            else None
        ),
        decay_at=(
            datetime.fromisoformat(str(data["decay_at"]))
            if data.get("decay_at") is not None
            else None
        ),
        category=MemoryCategory(data.get("category", "custom")),
        importance=MemoryImportance(data.get("importance", "normal")),
        confidence=float(data.get("confidence", 1.0)),
    )


def export_memories(storage: MemoryStorage, *, path: Path) -> int:
    """
    Body of MemoryManager.export(): write every stored memory to
    `path` as a JSON array. Returns the number of memories exported.
    """

    memories = storage.get_all()

    payload = {
        "format_version": _EXPORT_FORMAT_VERSION,
        "memories": [memory_to_json_dict(memory) for memory in memories],
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as ex:
        raise MemoryPersistenceError(f"Failed to export memories to '{path}'.") from ex

    return len(memories)


def import_memories(
    storage: MemoryStorage, *, path: Path, on_duplicate: str = "skip"
) -> int:
    """
    Body of MemoryManager.import_memories(): read a JSON export
    produced by `export_memories()` and insert every memory.

    Parameters
    ----------
    on_duplicate:
        "skip" (default) leaves an already-existing memory_id
        untouched; "replace" overwrites it.

    Returns
    -------
    int
        The number of memories actually inserted or replaced.
    """

    if on_duplicate not in ("skip", "replace"):
        raise ValueError("on_duplicate must be 'skip' or 'replace'.")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as ex:
        raise MemoryPersistenceError(f"Failed to read import file '{path}'.") from ex
    except json.JSONDecodeError as ex:
        raise MemoryPersistenceError(f"Import file '{path}' is not valid JSON.") from ex

    raw_memories = raw.get("memories", []) if isinstance(raw, dict) else raw

    imported = 0

    for entry in raw_memories:
        memory = memory_from_json_dict(entry)
        exists = storage.exists(memory.memory_id)

        if exists and on_duplicate == "skip":
            continue

        if exists:
            storage.update(memory)
        else:
            storage.insert(memory)

        imported += 1

    return imported
