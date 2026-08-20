"""
PARIKA Memory Remember/Merge

Implementation bodies for MemoryManager's high-level, duplicate-aware
`remember()` convenience API and its explicit `merge()` counterpart.

`remember()` is the primary entry point every other component (the
memory-as-tool capability, CLI commands) should use to create a
persistent memory: unlike `register()` (which always inserts a brand
new row and raises if the id already exists), `remember()` first
checks whether `content` is a recognized structured fact (see
`structured_facts.py`) and, if so, merges it into that group's single
canonical memory; otherwise it searches for an existing, sufficiently
similar memory in the same scope/category and, if found, updates that
canonical memory (bumping its confidence and adopting the new
content) instead of creating a duplicate -- see
`docs/architecture/PARIKA Phase 1 Completion Specification.md`
section 7 ("Duplicate Detection") and the PARIKA Memory Subsystem
Refactor's "Memory Validation" requirement (Ignore / Reuse / Update /
Merge / Create).

Nothing here performs semantic search or generates an embedding: the
duplicate check uses `duplicate_detection.find_duplicate()`, a
deterministic, stdlib-only lexical similarity ratio.
"""

from __future__ import annotations

from datetime import datetime, UTC
from types import MappingProxyType
from uuid import uuid4

from parika.core.memory_manager.duplicate_detection import (
    DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
    find_duplicate,
)
from parika.core.memory_manager.exceptions import MemoryNotFoundError
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import (
    MemoryImportance,
    default_score_for,
)
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.memory_manager.memory_scope import MemoryScope
from parika.core.memory_manager.postgresql_storage import PostgreSQLMemoryStorage
from parika.core.memory_manager.structured_facts import (
    SlotMatch,
    extract_slot,
    render_structured_content,
)

_CONFIDENCE_BUMP_ON_DUPLICATE: float = 0.1
_DUPLICATE_CANDIDATE_POOL: int = 20


def remember(
    storage: PostgreSQLMemoryStorage,
    *,
    content: str,
    category: MemoryCategory,
    kind: MemoryKind,
    origin: MemoryOrigin,
    scope: MemoryScope,
    session_id: str | None,
    importance: MemoryImportance,
    importance_score: float | None,
    confidence: float,
    tags: frozenset[str],
    metadata: dict[str, object],
    duplicate_similarity_threshold: float = DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
) -> tuple[Memory, bool]:
    """
    Body of MemoryManager.remember().

    Returns
    -------
    tuple[Memory, bool]
        The stored (new-or-merged) memory, and whether it was newly
        created (True) or merged into an existing duplicate (False).
    """

    slot_match = extract_slot(content)

    if slot_match is not None:
        return _remember_structured(
            storage,
            slot_match,
            session_id=session_id,
            importance=importance,
            importance_score=importance_score,
            confidence=confidence,
            tags=tags,
            metadata=metadata,
            now=datetime.now(UTC),
        )

    candidates = storage.search_candidates(
        text=content,
        scope=scope.value,
        session_id=None,  # a permanent memory can duplicate across sessions
        kind=None,
        pool_size=_DUPLICATE_CANDIDATE_POOL,
        category=category.value,
        # High-precision (AND) candidate search: a too-broad (OR)
        # pool here would let unrelated-but-lexically-overlapping
        # memories reach the difflib similarity check below and be
        # incorrectly merged -- see search_storage.search_candidates()'s
        # docstring.
        require_all_terms=True,
    )

    duplicate = find_duplicate(
        tuple(memory for memory, _rank in candidates),
        content,
        threshold=duplicate_similarity_threshold,
    )

    now = datetime.now(UTC)

    if duplicate is not None:
        merged = _merge_into(
            duplicate,
            new_content=content,
            now=now,
            importance=importance,
            importance_score=importance_score,
        )
        stored = storage.update(merged)

        if stored is None:
            raise MemoryNotFoundError(
                f"Memory '{duplicate.memory_id}' was not found during merge."
            )

        return stored, False

    resolved_importance_score = (
        importance_score if importance_score is not None else default_score_for(importance)
    )

    new_memory = Memory(
        memory_id=uuid4().hex,
        kind=kind,
        origin=origin,
        content=content,
        created_at=now,
        updated_at=now,
        tags=tags,
        metadata=MappingProxyType(metadata),
        scope=scope,
        session_id=session_id,
        importance_score=resolved_importance_score,
        category=category,
        importance=importance,
        confidence=confidence,
    )

    return storage.insert(new_memory), True


def _remember_structured(
    storage: MemoryStorage,
    slot_match: SlotMatch,
    *,
    session_id: str | None,
    importance: MemoryImportance,
    importance_score: float | None,
    confidence: float,
    tags: frozenset[str],
    metadata: dict[str, object],
    now: datetime,
) -> tuple[Memory, bool]:
    """
    Body of `remember()`'s Semantic Merge path (PARIKA Memory
    Subsystem Refactor Requirement D): find the single canonical
    memory already tracking `slot_match.group_key` (if any) and merge
    this new slot value into it, updating that slot in place if it
    was already present -- this is what makes a later, more specific
    restatement of the *same* slot (e.g. "preferred language: Python"
    -> "Python 3.14") an update rather than a duplicate, exactly like
    "Preferred transport"/"Preferred seat" merging into one Travel
    Preferences memory, or "Name"/"Nickname" merging into one Profile
    memory. Never touches any other group's memory (Isolation).
    """

    existing_candidates = storage.get_by_category(slot_match.category.value)

    existing = next(
        (
            memory
            for memory in existing_candidates
            if memory.metadata.get("structured_group") == slot_match.group_key
        ),
        None,
    )

    resolved_importance_score = (
        importance_score if importance_score is not None else default_score_for(importance)
    )

    if existing is not None:
        slots = dict(existing.metadata.get("slots") or {})
        slots[slot_match.slot_name] = slot_match.value

        merged_metadata = dict(existing.metadata)
        merged_metadata["structured_group"] = slot_match.group_key
        merged_metadata["slots"] = slots

        merged = Memory(
            memory_id=existing.memory_id,
            kind=existing.kind,
            origin=existing.origin,
            content=render_structured_content(slot_match.group_title, slots),
            created_at=existing.created_at,
            updated_at=now,
            tags=existing.tags | tags,
            metadata=MappingProxyType(merged_metadata),
            scope=existing.scope,
            session_id=existing.session_id,
            importance_score=max(
                existing.importance_score, resolved_importance_score
            ),
            access_count=existing.access_count,
            last_accessed_at=existing.last_accessed_at,
            decay_at=existing.decay_at,
            category=existing.category,
            importance=(
                importance
                if _importance_rank(importance) > _importance_rank(existing.importance)
                else existing.importance
            ),
            confidence=min(1.0, existing.confidence + _CONFIDENCE_BUMP_ON_DUPLICATE),
        )

        stored = storage.update(merged)

        if stored is None:
            raise MemoryNotFoundError(
                f"Memory '{existing.memory_id}' was not found during merge."
            )

        return stored, False

    slots = {slot_match.slot_name: slot_match.value}
    new_metadata = dict(metadata)
    new_metadata["structured_group"] = slot_match.group_key
    new_metadata["slots"] = slots

    new_memory = Memory(
        memory_id=uuid4().hex,
        kind=MemoryKind.FACT,
        origin=MemoryOrigin.USER_EXPLICIT,
        content=render_structured_content(slot_match.group_title, slots),
        created_at=now,
        updated_at=now,
        tags=tags,
        metadata=MappingProxyType(new_metadata),
        scope=MemoryScope.GLOBAL,
        session_id=session_id,
        importance_score=resolved_importance_score,
        category=slot_match.category,
        importance=importance,
        confidence=confidence,
    )

    return storage.insert(new_memory), True


def _merge_into(
    existing: Memory,
    *,
    new_content: str,
    now: datetime,
    importance: MemoryImportance,
    importance_score: float | None,
) -> Memory:
    """
    Merge new content into an existing canonical memory: bumps
    confidence (capped at 1.0), refreshes `updated_at`, and adopts
    `new_content` as the canonical content.

    Adopting the new restatement (rather than discarding it) is what
    makes this the same mechanism satisfying both "Reuse" (near-
    identical restatements, where the adopted text is indistinguishable
    from the original) and "Semantic Update" (PARIKA Memory Subsystem
    Refactor Requirement D) -- e.g. "preferred language: Python"
    followed by a near-duplicate-worded "preferred language: Python
    3.14" replaces the stale value instead of preserving it.
    """

    resolved_importance_score = (
        importance_score
        if importance_score is not None
        else max(existing.importance_score, default_score_for(importance))
    )

    return Memory(
        memory_id=existing.memory_id,
        kind=existing.kind,
        origin=existing.origin,
        content=new_content,
        created_at=existing.created_at,
        updated_at=now,
        tags=existing.tags,
        metadata=existing.metadata,
        scope=existing.scope,
        session_id=existing.session_id,
        importance_score=resolved_importance_score,
        access_count=existing.access_count,
        last_accessed_at=existing.last_accessed_at,
        decay_at=existing.decay_at,
        category=existing.category,
        importance=(
            importance
            if _importance_rank(importance) > _importance_rank(existing.importance)
            else existing.importance
        ),
        confidence=min(1.0, existing.confidence + _CONFIDENCE_BUMP_ON_DUPLICATE),
    )


def merge(
    storage: PostgreSQLMemoryStorage, *, primary_id: str, secondary_id: str
) -> tuple[Memory, Memory]:
    """
    Body of MemoryManager.merge(): explicitly merge `secondary_id`
    into `primary_id`, combining tags/metadata, keeping the primary's
    content as canonical, bumping confidence, and deleting the
    secondary memory.

    Returns
    -------
    tuple[Memory, Memory]
        The merged (updated) primary memory, and the deleted secondary
        memory (as it existed immediately before deletion).
    """

    primary = storage.get(primary_id)
    secondary = storage.get(secondary_id)

    if primary is None:
        raise MemoryNotFoundError(f"Memory '{primary_id}' was not found.")

    if secondary is None:
        raise MemoryNotFoundError(f"Memory '{secondary_id}' was not found.")

    merged_metadata = dict(primary.metadata)
    merged_metadata.update(dict(secondary.metadata))

    merged = Memory(
        memory_id=primary.memory_id,
        kind=primary.kind,
        origin=primary.origin,
        content=primary.content,
        created_at=primary.created_at,
        updated_at=datetime.now(UTC),
        tags=primary.tags | secondary.tags,
        metadata=MappingProxyType(merged_metadata),
        scope=primary.scope,
        session_id=primary.session_id,
        importance_score=max(primary.importance_score, secondary.importance_score),
        access_count=primary.access_count + secondary.access_count,
        last_accessed_at=primary.last_accessed_at,
        decay_at=primary.decay_at,
        category=primary.category,
        importance=(
            primary.importance
            if _importance_rank(primary.importance) >= _importance_rank(secondary.importance)
            else secondary.importance
        ),
        confidence=min(1.0, primary.confidence + _CONFIDENCE_BUMP_ON_DUPLICATE),
    )

    stored = storage.update(merged)

    if stored is None:
        raise MemoryNotFoundError(f"Memory '{primary_id}' was not found during merge.")

    deleted_secondary = storage.delete(secondary_id)

    if deleted_secondary is None:
        deleted_secondary = secondary

    return stored, deleted_secondary


def _importance_rank(importance: MemoryImportance) -> int:
    return {
        MemoryImportance.LOW: 0,
        MemoryImportance.NORMAL: 1,
        MemoryImportance.HIGH: 2,
        MemoryImportance.CRITICAL: 3,
    }[importance]
