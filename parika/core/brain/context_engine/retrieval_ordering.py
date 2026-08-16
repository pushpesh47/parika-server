"""
PARIKA Brain - Context Engine - Retrieval Ordering

Assembles a token-budget-aware context bundle for a Goal by reading
MemoryManager.search() and KnowledgeManager.search() (both already
score-ranked -- see
docs/architecture/Intelligence_Foundation_Design.md sections 4 and 5)
and greedily packing the highest score-per-token candidates until the
budget is exhausted.

Per the Phase 1 Completion Specification (sections 3-4, 13-14, 20-21),
this is Context Assembly: it integrates Session (the current
conversation), Memory, Knowledge, and Experience into one
ContextBundle before Planner ever runs. Experience never contributes
retrieved *content* here (Experience "never replaces Memory" -- see
section 14): it only reports a diagnostic success-rate summary,
reusing Planner's own `ExperienceSource` Protocol so this module never
gains a new dependency direction. The mechanism through which
Experience actually *influences* planning/provider/tool ranking
remains `ExperienceRule` inside `planner/model_selection/`, unchanged.

This module performs pure orchestration: it never parses, embeds, or
otherwise interprets content itself -- all real retrieval work stays
inside MemoryManager/KnowledgeManager, exactly matching the boundary
Planner's `model_selection/` already keeps with ProviderManager/
ToolManager.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import NamedTuple, TYPE_CHECKING

from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.search_result import SearchResult
from parika.core.memory_manager.memory_search_query import MemorySearchQuery
from parika.core.memory_manager.scored_memory import ScoredMemory

from .budget import TokenBudget
from .token_estimator import TokenEstimator

if TYPE_CHECKING:
    from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
    from parika.core.memory_manager.memory_manager import MemoryManager
    from parika.core.planner.goal import Goal
    from parika.core.planner.model_selection.experience_source import ExperienceSource

_NULL_LOGGER = logging.getLogger("parika.core.brain.context_engine.null")
_NULL_LOGGER.addHandler(logging.NullHandler())


class _Candidate(NamedTuple):
    score: float
    token_estimate: int
    memory: ScoredMemory | None
    knowledge: SearchResult | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextBundle:
    """The result of one `assemble_context()` call."""

    memories: tuple[ScoredMemory, ...] = field(default_factory=tuple)
    knowledge: tuple[SearchResult, ...] = field(default_factory=tuple)
    conversation_message_count: int = 0
    experience_success_rate: float | None = None
    estimated_tokens: int = 0
    budget: TokenBudget = field(default_factory=TokenBudget)


def assemble_context(
    *,
    goal: "Goal",
    memory_manager: "MemoryManager | None",
    knowledge_manager: "KnowledgeManager | None",
    budget: TokenBudget,
    estimator: TokenEstimator,
    experience_source: "ExperienceSource | None" = None,
    conversation_message_count: int = 0,
    memory_search_limit: int | None = None,
    knowledge_search_limit: int | None = None,
    logger: logging.Logger = _NULL_LOGGER,
) -> ContextBundle:
    """
    Build a token-budget-aware ContextBundle for `goal`, integrating
    Session, Memory, Knowledge, and Experience (see this module's
    docstring).

    Uses the well-known `Goal.inputs["message"]` convention (the same
    one Requirement Inference already reads) as the search text. When
    absent, Knowledge search is skipped entirely (its `SearchQuery`
    requires non-empty text); Memory search still runs with an empty
    query text, which falls back to its recency/importance/frequency
    ranking (see `MemorySearchQuery`).

    `memory_search_limit`/`knowledge_search_limit` bound only how many
    already-ranked candidates are *fetched* for consideration, never
    how many end up in the final `ContextBundle` -- that is decided
    exclusively by the greedy, score-per-token packing below against
    `budget.usable_tokens`. When omitted (the default), the fetch
    limit itself is derived from `budget.usable_tokens` rather than a
    hardcoded count: every candidate costs at least one token, so
    `budget.usable_tokens` candidates is always enough to give the
    packer full visibility into everything that could conceivably fit,
    and it scales with the Runtime Context Budget (a larger selected
    model's context window fetches a larger candidate pool) instead of
    being fixed regardless of budget.
    """

    effective_memory_search_limit = (
        memory_search_limit
        if memory_search_limit is not None
        else max(1, budget.usable_tokens)
    )
    effective_knowledge_search_limit = (
        knowledge_search_limit
        if knowledge_search_limit is not None
        else max(1, budget.usable_tokens)
    )

    message = goal.inputs.get("message")
    text = message if isinstance(message, str) else ""

    logger.debug("Context Assembly: searching conversation history...")
    logger.debug(
        "Context Assembly: conversation hits=%d", conversation_message_count
    )

    candidates: list[_Candidate] = []

    logger.debug("Context Assembly: searching permanent memory...")
    memory_hits = 0

    if memory_manager is not None:
        # Deliberately no `session_id` filter: a permanent memory is,
        # by definition, meant to be retrieved regardless of which
        # session created it (Phase 1 Completion Specification section
        # 1, "independent from conversation history") -- ranking
        # (relevance/recency/importance/frequency) is what surfaces
        # the most useful memories, not a hard session boundary.
        memory_results = memory_manager.search(
            MemorySearchQuery(text=text, limit=effective_memory_search_limit)
        )
        memory_hits = len(memory_results)

        for result in memory_results:
            token_estimate = estimator.estimate(result.memory.content)
            candidates.append(
                _Candidate(
                    score=result.score, token_estimate=token_estimate,
                    memory=result, knowledge=None,
                )
            )

    logger.debug("Context Assembly: memory hits=%d", memory_hits)

    logger.debug("Context Assembly: searching knowledge...")
    knowledge_hits = 0

    if knowledge_manager is not None and text.strip():
        knowledge_results = knowledge_manager.search(
            SearchQuery(text=text, limit=effective_knowledge_search_limit)
        )
        knowledge_hits = len(knowledge_results)

        for knowledge_result in knowledge_results:
            token_estimate = estimator.estimate(knowledge_result.knowledge.content)
            candidates.append(
                _Candidate(
                    score=knowledge_result.score, token_estimate=token_estimate,
                    memory=None, knowledge=knowledge_result,
                )
            )

    logger.debug("Context Assembly: knowledge hits=%d", knowledge_hits)

    logger.debug("Context Assembly: searching experience...")
    experience_success_rate: float | None = None

    if experience_source is not None:
        capability_id = goal.capability_id

        try:
            experience_success_rate = experience_source.aggregate_outcome_rate(
                capability_id=capability_id
            )
        except Exception:
            # Never let an unavailable/uninitialized Experience backend
            # break Context Assembly -- degrade to "no data", matching
            # ExperienceRule's identical graceful-degradation contract.
            experience_success_rate = None

    logger.debug(
        "Context Assembly: experience hits=%d",
        0 if experience_success_rate is None else 1,
    )

    # Greedily pack by value density (score per token) until the usable
    # Runtime Context Budget alone is exhausted -- Context Assembly
    # uses as much relevant Memory/Knowledge content as fits within
    # `budget.usable_tokens`, never a fixed entry count independent of
    # the budget (Phase A.5).
    candidates.sort(
        key=lambda candidate: candidate.score / max(1, candidate.token_estimate),
        reverse=True,
    )

    remaining_tokens = budget.usable_tokens
    included_memories: list[ScoredMemory] = []
    included_knowledge: list[SearchResult] = []
    used_tokens = 0

    for candidate in candidates:
        if candidate.token_estimate > remaining_tokens:
            continue

        if candidate.memory is not None:
            included_memories.append(candidate.memory)
        elif candidate.knowledge is not None:
            included_knowledge.append(candidate.knowledge)

        remaining_tokens -= candidate.token_estimate
        used_tokens += candidate.token_estimate

    logger.debug(
        "Context Assembly: context assembled (memories=%d, knowledge=%d, "
        "context_tokens=%d)",
        len(included_memories),
        len(included_knowledge),
        used_tokens,
    )

    return ContextBundle(
        memories=tuple(included_memories),
        knowledge=tuple(included_knowledge),
        conversation_message_count=conversation_message_count,
        experience_success_rate=experience_success_rate,
        estimated_tokens=used_tokens,
        budget=budget,
    )
