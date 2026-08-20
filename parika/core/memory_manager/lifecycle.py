"""
PARIKA Memory Lifecycle

Implementation bodies for MemoryManager's retrieval, lifecycle, and
consolidation/pruning operations (get_by_scope, get_by_kind, touch,
search, consolidation_candidates, prune).

Extracted from memory_manager.py to keep each file within the project's
file-size guideline (see PARIKA_Core_Coding_Standards.md). MemoryManager
remains the package's single public class and entry point: it performs
input validation and holds the thread lock, then delegates the actual
body of each operation to a function here. Nothing outside
memory_manager.py imports this module.

Every function here is mechanical: SQL-shaped filtering, deterministic
scoring arithmetic, and structural comparisons. Nothing here reasons
about memory content, summarizes it, or generates an embedding.
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, UTC

from parika.core.event_bus.event_bus import EventBus
from parika.core.memory_manager.config import MemoryManagerConfig
from parika.core.memory_manager.consolidation_policy import ConsolidationPolicy
from parika.core.memory_manager.events import MemoryRemovedEvent
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_search_query import MemorySearchQuery
from parika.core.memory_manager.prune_policy import PrunePolicy
from parika.core.memory_manager.retrieval import rank_candidates
from parika.core.memory_manager.scored_memory import ScoredMemory
from parika.core.memory_manager.postgresql_storage import PostgreSQLMemoryStorage


def search(
    storage: PostgreSQLMemoryStorage, *, query: MemorySearchQuery, config: MemoryManagerConfig
) -> tuple[ScoredMemory, ...]:
    """Body of MemoryManager.search()."""

    pool_size = max(
        query.limit + query.offset,
        (query.limit + query.offset) * config.candidate_pool_multiplier,
    )

    candidates = storage.search_candidates(
        text=query.text,
        scope=query.scope.value if query.scope is not None else None,
        session_id=query.session_id,
        kind=query.kind.value if query.kind is not None else None,
        pool_size=pool_size,
        category=query.category.value if query.category is not None else None,
    )

    return rank_candidates(
        candidates, config=config, limit=query.limit, offset=query.offset
    )


def consolidation_candidates(
    storage: PostgreSQLMemoryStorage, *, policy: ConsolidationPolicy
) -> tuple[Memory, ...]:
    """Body of MemoryManager.consolidation_candidates()."""

    older_than = datetime.now(UTC) - timedelta(seconds=policy.older_than_seconds)

    return storage.select_stale(
        scope=policy.scope.value,
        session_id=policy.session_id,
        kind=policy.kind.value,
        older_than=older_than,
        max_access_count=policy.max_access_count,
    )


def prune(
    storage: PostgreSQLMemoryStorage,
    *,
    policy: PrunePolicy,
    event_bus: EventBus,
    logger: logging.Logger,
) -> tuple[Memory, ...]:
    """
    Body of MemoryManager.prune(). Deletes candidates and publishes a
    `memory.removed` event per removed memory, reusing the same event
    already published by MemoryManager.remove().
    """

    candidates: dict[str, Memory] = {}

    if policy.respect_decay:
        for memory in storage.select_expired(now=datetime.now(UTC)):
            candidates[memory.memory_id] = memory

    if policy.max_per_scope is not None:
        for memory in storage.select_excess(
            scope=policy.scope.value if policy.scope is not None else None,
            session_id=policy.session_id,
            keep_count=policy.max_per_scope,
        ):
            candidates[memory.memory_id] = memory

    if not candidates:
        return ()

    removed = storage.delete_many(tuple(candidates.keys()))

    for memory in removed:
        logger.info("Pruned memory '%s'.", memory.memory_id)

        event_bus.publish(
            event_name="memory.removed",
            payload=MemoryRemovedEvent(memory=memory),
        )

    return removed
