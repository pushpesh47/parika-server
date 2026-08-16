"""
PARIKA Memory Bulk Operations

Implementation bodies for MemoryManager's `list()`, `clear()`, and
`stats()` -- mechanical, filter-shaped bulk read/delete/aggregate
operations, none of which interpret memory content.
"""

from __future__ import annotations

import logging
import os

from pathlib import Path
from types import MappingProxyType

from parika.core.event_bus.event_bus import EventBus
from parika.core.memory_manager.events import MemoryRemovedEvent
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_scope import MemoryScope
from parika.core.memory_manager.memory_stats import MemoryStats
from parika.core.memory_manager.storage import MemoryStorage


def list_memories(
    storage: MemoryStorage,
    *,
    category: MemoryCategory | None,
    scope: MemoryScope | None,
    session_id: str | None,
    limit: int | None,
) -> tuple[Memory, ...]:
    """Body of MemoryManager.list()."""

    return storage.list_memories(
        category=category.value if category is not None else None,
        scope=scope.value if scope is not None else None,
        session_id=session_id,
        limit=limit,
    )


def clear(
    storage: MemoryStorage,
    *,
    category: MemoryCategory | None,
    scope: MemoryScope | None,
    session_id: str | None,
    event_bus: EventBus,
    logger: logging.Logger,
) -> tuple[Memory, ...]:
    """
    Body of MemoryManager.clear(): delete every memory matching the
    optional filters (no filters = every memory), publishing a
    `memory.removed` event per removed memory, same as prune()/remove().
    """

    removed = storage.delete_all(
        category=category.value if category is not None else None,
        scope=scope.value if scope is not None else None,
        session_id=session_id,
    )

    for memory in removed:
        logger.info("Cleared memory '%s'.", memory.memory_id)

        event_bus.publish(
            event_name="memory.removed",
            payload=MemoryRemovedEvent(memory=memory),
        )

    return removed


def stats(storage: MemoryStorage, *, database_path: Path) -> MemoryStats:
    """Body of MemoryManager.stats()."""

    total = storage.count()
    by_category = storage.count_by(column="category")
    by_importance = storage.count_by(column="importance")
    by_scope = storage.count_by(column="scope")

    storage_size_bytes = 0

    try:
        storage_size_bytes = os.path.getsize(database_path)
    except OSError:
        storage_size_bytes = 0

    return MemoryStats(
        total=total,
        by_category=MappingProxyType(by_category),
        by_importance=MappingProxyType(by_importance),
        by_scope=MappingProxyType(by_scope),
        storage_size_bytes=storage_size_bytes,
    )
