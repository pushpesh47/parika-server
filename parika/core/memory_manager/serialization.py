"""
PARIKA Memory Serialization

Pure serialization/deserialization helpers converting between the
immutable Memory domain model and SQLite row representations.

This module contains no connection handling, no schema management, and
no business logic -- only structural conversion.
"""

from __future__ import annotations

import json
import sqlite3

from datetime import datetime
from types import MappingProxyType

from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import MemoryImportance
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.memory_manager.memory_scope import MemoryScope

type SerializedMemory = tuple[
    str,  # memory_id
    str,  # kind
    str,  # origin
    str,  # content
    str,  # created_at
    str,  # updated_at
    str,  # tags
    str,  # metadata
    str,  # scope
    str | None,  # session_id
    float,  # importance_score
    int,  # access_count
    str | None,  # last_accessed_at
    str | None,  # decay_at
    str,  # category
    str,  # importance
    float,  # confidence
]


def serialize_memory(memory: Memory) -> SerializedMemory:
    """
    Serialize a Memory object into a SQLite row.

    Parameters
    ----------
    memory:
        Memory to serialize.

    Returns
    -------
    SerializedMemory
        SQLite-compatible row values.
    """

    return (
        memory.memory_id,
        memory.kind.value,
        memory.origin.value,
        memory.content,
        memory.created_at.isoformat(),
        memory.updated_at.isoformat(),
        json.dumps(sorted(memory.tags), ensure_ascii=False),
        json.dumps(
            dict(memory.metadata),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        memory.scope.value,
        memory.session_id,
        memory.importance_score,
        memory.access_count,
        memory.last_accessed_at.isoformat() if memory.last_accessed_at is not None else None,
        memory.decay_at.isoformat() if memory.decay_at is not None else None,
        memory.category.value,
        memory.importance.value,
        memory.confidence,
    )


def deserialize_memory(row: sqlite3.Row) -> Memory:
    """
    Deserialize a SQLite row into a Memory object.

    Parameters
    ----------
    row:
        SQLite row.

    Returns
    -------
    Memory
        Deserialized Memory object.
    """

    return Memory(
        memory_id=row["memory_id"],
        kind=MemoryKind(row["kind"]),
        origin=MemoryOrigin(row["origin"]),
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        tags=frozenset(json.loads(row["tags"])),
        metadata=MappingProxyType(json.loads(row["metadata"])),
        scope=MemoryScope(row["scope"]),
        session_id=row["session_id"],
        importance_score=float(row["importance_score"]),
        access_count=int(row["access_count"]),
        last_accessed_at=(
            datetime.fromisoformat(row["last_accessed_at"])
            if row["last_accessed_at"] is not None
            else None
        ),
        decay_at=(
            datetime.fromisoformat(row["decay_at"])
            if row["decay_at"] is not None
            else None
        ),
        category=MemoryCategory(row["category"]),
        importance=MemoryImportance(row["importance"]),
        confidence=float(row["confidence"]),
    )
