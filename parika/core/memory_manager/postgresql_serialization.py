"""
PARIKA Memory Serialization - PostgreSQL Implementation

Serialization/deserialization of Memory objects for PostgreSQL storage.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import MemoryImportance
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.memory_manager.memory_scope import MemoryScope


def serialize_memory(memory: Memory) -> tuple:
    """Serialize a Memory object to a tuple for PostgreSQL insertion."""
    return (
        memory.memory_id,
        memory.kind.value,
        memory.origin.value,
        memory.content,
        memory.created_at.isoformat(),
        memory.updated_at.isoformat(),
        json.dumps(list(memory.tags), ensure_ascii=False),
        json.dumps(dict(memory.metadata), ensure_ascii=False),
        memory.scope.value,
        memory.session_id,
        memory.importance_score,
        memory.access_count,
        memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
        memory.decay_at.isoformat() if memory.decay_at else None,
        memory.category.value,
        memory.importance.value,
        memory.confidence,
    )


def deserialize_memory(row) -> Memory:
    """Deserialize a PostgreSQL row to a Memory object."""
    tags = row["tags"]
    if isinstance(tags, str):
        tags = frozenset(json.loads(tags))
    elif isinstance(tags, list):
        tags = frozenset(tags)
    else:
        tags = frozenset()

    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = MappingProxyType(json.loads(metadata))
    elif isinstance(metadata, dict):
        metadata = MappingProxyType(metadata)
    else:
        metadata = MappingProxyType({})

    last_accessed_at = row["last_accessed_at"]
    if isinstance(last_accessed_at, str):
        last_accessed_at = datetime.fromisoformat(last_accessed_at)

    decay_at = row["decay_at"]
    if isinstance(decay_at, str):
        decay_at = datetime.fromisoformat(decay_at)

    return Memory(
        memory_id=row["memory_id"],
        kind=MemoryKind(row["kind"]),
        origin=MemoryOrigin(row["origin"]),
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        tags=tags,
        metadata=metadata,
        scope=MemoryScope(row["scope"]),
        session_id=row["session_id"],
        importance_score=row["importance_score"],
        access_count=row["access_count"],
        last_accessed_at=last_accessed_at,
        decay_at=decay_at,
        category=MemoryCategory(row["category"]),
        importance=MemoryImportance(row["importance"]),
        confidence=row["confidence"],
    )