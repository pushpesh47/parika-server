"""
PARIKA AI Context Engineering - Session Context

Owns ONLY retrieving read-only excerpts from previously saved sessions
(Session Store) and rendering them into system-prompt-ready text, for
a turn explicitly asking about past/previous conversations. Never
retrieves or renders Memory/Knowledge (see `context_builder.py`) and
never touches the current, rolling conversation history (see
`conversation.py`).

Phase A.5: how many saved-session excerpts get injected, and how many
distinct sessions get sampled for the no-topic-keyword fallback, are no
longer fixed counts (`SESSION_RETRIEVAL_RESULT_LIMIT`,
`SESSION_RETRIEVAL_RECENT_SESSION_LIMIT`) -- both are now driven by the
caller-supplied `token_budget` (the portion of the Runtime Context
Budget left over after Memory/Knowledge Context Assembly), via
`_take_within_budget()`/`_recent_session_excerpts()`. A larger budget
(a model with a bigger context window, or less content already used by
Memory/Knowledge) surfaces more previous-session content; a smaller one
surfaces less. This still never scans every saved session (Bug #8,
performance): the number of sessions scanned is itself bounded by
`token_budget`, since each contributed excerpt costs at least one
token.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..session_intent import extract_session_search_topic, has_session_retrieval_intent
from ..session_store import SessionMessage, SessionPersistenceError, SqliteSessionStore
from parika.core.brain.context_engine import HeuristicTokenEstimator, TokenEstimator
from parika.core.provider_manager.chat_message import ChatMessage

SESSION_RETRIEVAL_EXCERPT_MAX_CHARS = 240
"""
Per-message excerpt truncation length. This is rendering/formatting of
one already-selected excerpt (bounding how much of a single message is
quoted), not a fixed-count prompt limitation on how many excerpts are
included -- that is `token_budget`-driven (see module docstring) -- so
it is out of Phase A.5's scope.
"""


def _truncate(text: str, max_chars: int) -> str:
    """Truncate `text` to `max_chars`, appending an ellipsis if cut."""

    stripped = text.strip()

    if len(stripped) <= max_chars:
        return stripped

    return stripped[: max_chars - 1].rstrip() + "\u2026"


def _rendered_token_cost(message: SessionMessage, *, estimator: TokenEstimator) -> int:
    """Token cost of one excerpt as it will actually be rendered (truncated)."""

    return estimator.estimate(
        _truncate(message.content, SESSION_RETRIEVAL_EXCERPT_MAX_CHARS)
    )


def _take_within_budget(
    messages: Iterable[SessionMessage],
    *,
    token_budget: int,
    estimator: TokenEstimator,
) -> tuple[SessionMessage, ...]:
    """
    Greedily keep messages (in the given, already-relevance-ordered
    order) whose rendered token cost fits within `token_budget`,
    skipping over any single excerpt too large to fit rather than
    stopping early -- the same "skip, don't stop" packing behavior
    `context_engine.retrieval_ordering.assemble_context()` already
    uses for Memory/Knowledge.
    """

    selected: list[SessionMessage] = []
    used_tokens = 0

    for message in messages:
        cost = _rendered_token_cost(message, estimator=estimator)

        if used_tokens + cost > token_budget:
            continue

        selected.append(message)
        used_tokens += cost

    return tuple(selected)


def _recent_session_excerpts(
    session_store: SqliteSessionStore,
    *,
    exclude_session_id: str | None,
    token_budget: int,
    estimator: TokenEstimator,
) -> tuple[SessionMessage, ...]:
    """
    Fall back to the most recently updated saved sessions' own
    messages when a session-retrieval request has no extractable
    topic keyword to search for (see `extract_session_search_topic()`)
    -- e.g. "Summarize our previous discussions.", "Search previous
    sessions and introduce me."

    Bounded by `token_budget` rather than a fixed excerpt/session
    count (Phase A.5): both how many excerpts are kept and how many
    distinct sessions are ever scanned scale with the available
    Runtime Context Budget, never a hardcoded number -- this still
    never scans every saved session (Bug #8, performance), since each
    contributed excerpt costs at least one token, so scanning more
    sessions than `token_budget` could ever justify is pointless.
    """

    try:
        summaries = session_store.list_sessions()
    except SessionPersistenceError:
        return ()

    max_sessions_to_scan = max(1, token_budget)
    excerpts: list[SessionMessage] = []
    used_tokens = 0
    sessions_scanned = 0

    for summary in summaries:
        if summary.session_id == exclude_session_id:
            continue

        if sessions_scanned >= max_sessions_to_scan or used_tokens >= token_budget:
            break

        sessions_scanned += 1

        try:
            messages = session_store.get_messages(summary.session_id)
        except SessionPersistenceError:
            continue

        for message in messages[-2:]:
            if message.role not in ("user", "assistant"):
                continue

            cost = _rendered_token_cost(message, estimator=estimator)

            if used_tokens + cost > token_budget:
                continue

            excerpts.append(message)
            used_tokens += cost

    return tuple(excerpts)


def assemble_session_retrieval_messages(
    *,
    text: str,
    session_store: SqliteSessionStore | None,
    current_session_id: str | None,
    token_budget: int,
    estimator: TokenEstimator | None = None,
) -> tuple[ChatMessage, ...]:
    """
    Retrieve read-only excerpts from previously saved sessions
    (Session Store) and render them as zero or one additional
    system-role, provider-independent `ChatMessage`, but only for a
    turn `session_intent.
    has_session_retrieval_intent()` recognizes as explicitly asking
    about past/previous conversations (PARIKA Memory & Session
    Retrieval Finalization, Bugs #4/#5/#8) -- e.g. "Search previous
    sessions for Docker.", "What did we discuss last week?", "Find
    where I mentioned Laravel.".

    Never called for an ordinary turn (Bug #8, performance): unlike
    Memory/Knowledge Context Assembly, which runs every turn via
    `context_builder.assemble_context_messages()`, this only ever runs
    `session_store.search_messages()`/`list_sessions()`/
    `get_messages()` -- entirely read-only calls that never create,
    modify, or merge anything into permanent Memory (Bug #6) -- when
    this turn's own text explicitly asks about saved sessions.

    Args:
        token_budget:
            Tokens still available in this turn's Runtime Context
            Budget for previous-session excerpts (typically what is
            left of `TokenBudget.usable_tokens` after Memory/Knowledge
            Context Assembly already spent some of it). Bounds both
            how many excerpts are injected and how many candidate
            sessions/messages are ever fetched or scanned (Phase A.5,
            replacing the old fixed `SESSION_RETRIEVAL_RESULT_LIMIT`/
            `SESSION_RETRIEVAL_RECENT_SESSION_LIMIT` counts) -- never
            an entire previous session's full content (Bug #7), and
            never the current session's own just-appended message
            (`current_session_id` is always excluded).

    Never raises: a Session Store failure degrades to "no additional
    context" rather than breaking the chat turn, matching
    `context_builder.assemble_context_messages()`'s own failure
    handling.
    """

    if (
        session_store is None
        or not has_session_retrieval_intent(text)
        or token_budget <= 0
    ):
        return ()

    active_estimator = estimator if estimator is not None else HeuristicTokenEstimator()

    topic = extract_session_search_topic(text)

    if topic is not None:
        # Every candidate costs at least one token, so `token_budget`
        # candidates is always enough to give the packing below full
        # visibility into everything that could conceivably fit --
        # scales with the Runtime Context Budget instead of a fixed
        # fetch count.
        try:
            matches = session_store.search_messages(topic, limit=max(1, token_budget))
        except SessionPersistenceError:
            matches = ()
    else:
        matches = _recent_session_excerpts(
            session_store,
            exclude_session_id=current_session_id,
            token_budget=token_budget,
            estimator=active_estimator,
        )

    candidates = (
        message
        for message in matches
        if message.session_id != current_session_id
        and message.role in ("user", "assistant")
    )
    excerpts = _take_within_budget(
        candidates, token_budget=token_budget, estimator=active_estimator
    )

    if not excerpts:
        content = (
            "No matching content was found in previously saved "
            "sessions for this request. This is separate from "
            "permanent memory and from the current conversation -- "
            "say honestly that no matching past session content was "
            "found, rather than guessing."
        )
    else:
        lines = "\n".join(
            f"- [{message.role} - session {message.session_id[:8]}]: "
            f"{_truncate(message.content, SESSION_RETRIEVAL_EXCERPT_MAX_CHARS)}"
            for message in excerpts
        )
        content = (
            "Relevant excerpts from previously saved sessions (a "
            "read-only, archived conversation history -- distinct "
            "from both permanent memory and this current "
            "conversation; never store, modify, or merge anything "
            "into memory based on this):\n" + lines
        )

    return (ChatMessage(role="system", content=content),)
