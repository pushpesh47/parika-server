"""
PARIKA Interfaces - Session Retrieval Intent Detection

Deterministic, keyword-based detection of whether a user message is
asking about a *previously saved session* (an archived past
conversation, distinct from both the current conversation and
permanent Memory) -- see `ai_context.session_context.
assemble_session_retrieval_messages()`, which this module gates.

PARIKA has three distinct knowledge sources for a chat turn:

1. The current conversation -- ordinary rolling message history,
   already visible to the model with no retrieval needed.
2. Permanent Memory -- facts the user explicitly asked to remember
   (see `parika.tools.memory.intent`), retrieved automatically via
   Context Assembly (`Brain.assemble_context()`).
3. Saved Sessions -- archived past conversations, persisted by
   `PostgreSQLSessionStore` (already used by the CLI's `/sessions search`)
   but previously unreachable from natural language at all.

This module recognizes source (3): explicit asks to search/recall
past/previous sessions, chats, or conversations (e.g. "Search previous
sessions for Docker.", "What did we discuss last week?", "Find where I
mentioned Laravel.", "Summarize our previous discussions."). It
deliberately does NOT fire for a question about the *current*
conversation (e.g. "Earlier in this conversation what did I say?") --
that is already answered directly from the rolling message history,
with no retrieval needed at all; see `_CURRENT_CONVERSATION_MARKER`.

Kept as a deterministic keyword rule, never an LLM call, matching
`parika.tools.memory.intent`'s own explicit-intent detection -- this
is what makes Session Retrieval only ever run "when the user
explicitly requests previous conversations" rather than scanning every
saved session on every ordinary turn (performance requirement). Unlike
the domain/tool-relevance keyword routing AI Context Engineering
removed (see `Request_Understanding.md`), this module recognizes
exactly one fixed, narrow intent -- "give me previously saved session
content" -- that never grows or needs updating when a new Capability
is registered, so it is not part of that removal.
"""

from __future__ import annotations

import re

_CURRENT_CONVERSATION_MARKER = re.compile(
    r"\b(?:this|current)\s+conversation\b"
    r"|\bin\s+this\s+chat\b"
    r"|\bjust\s+(?:said|mentioned|told|asked)\b"
    r"|\bwhat\s+did\s+i\s+(?:just\s+)?say\b",
    re.IGNORECASE,
)
"""
Marks a question as being about the *current* conversation (already
visible in the rolling message history, no retrieval needed) rather
than a previously saved session -- e.g. "Earlier in this conversation
what did I say?". Only suppresses session retrieval when the message
does not also explicitly mention a "session" -- a message could in
principle mention both.
"""

_SESSION_RETRIEVAL_PATTERN = re.compile(
    r"\b(?:previous|past|prior|earlier|last)\b[^.?!]{0,40}\b"
    r"(?:session|sessions|chat|chats|conversation|conversations|"
    r"discussion|discussions|talk|talks)\b"
    r"|\b(?:session|sessions|chat|chats|conversation|conversations)\b"
    r"[^.?!]{0,40}\b(?:previous|past|prior|earlier)\b"
    r"|\bsearch\b[^.?!]{0,60}\b(?:session|sessions|chat|chats|"
    r"conversation|conversations)\b"
    r"|\bfind\s+where\s+i\b"
    r"|\bwhat\s+did\s+we\s+discuss\b"
    r"|\bwhat\s+we\s+(?:discussed|talked\s+about|spoke\s+about)\b"
    r"|\b(?:summarize|summarise)\b[^.?!]{0,60}\b(?:previous|past|prior|"
    r"our)\b[^.?!]{0,60}\b(?:discussion|discussions|conversation|"
    r"conversations|chat|chats|session|sessions)\b",
    re.IGNORECASE,
)


def has_session_retrieval_intent(text: str) -> bool:
    """
    Return True if `text` is explicitly asking about a previously
    saved session -- e.g. "Search previous sessions for Docker.",
    "Find where I mentioned Laravel.", "What did we discuss last
    week?", "Summarize our previous discussions."

    Returns False for ordinary questions (no session retrieval should
    run at all -- performance requirement), for questions about the
    *current* conversation (e.g. "Earlier in this conversation what
    did I say?" -- already answered from rolling message history), and
    for permanent-memory questions (e.g. "What do you remember about
    me?" -- a different knowledge source entirely, see module
    docstring).
    """

    if _CURRENT_CONVERSATION_MARKER.search(text) and not re.search(
        r"\bsession", text, re.IGNORECASE
    ):
        return False

    return bool(_SESSION_RETRIEVAL_PATTERN.search(text))


_QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "about", "all", "an", "and", "any", "are", "can", "could",
        "chat", "chats", "conversation", "conversations", "did", "discuss",
        "discussed", "discussion", "discussions", "do", "does", "earlier",
        "find", "for", "from", "have", "i", "in", "introduce", "is", "it",
        "last", "me", "mention", "mentioned", "month", "my", "of", "on",
        "our", "past", "please", "previous", "prior", "recall", "said",
        "say", "search", "session", "sessions", "spoke", "speak", "summarise",
        "summarize", "talk", "talked", "talks", "tell", "that", "the",
        "this", "time", "to", "us", "was", "we", "week", "were", "what",
        "when", "where", "which", "will", "with", "would", "you", "your",
    }
)
"""
Small, curated stopword list used only by `extract_session_search_topic()`
to strip the *intent* phrasing itself (e.g. "search", "previous",
"sessions", "for") from a message, leaving only the actual topic
keyword (e.g. "Docker") to search for -- never used for anything else,
in particular never for `has_session_retrieval_intent()` itself.
"""

_WORD_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+#.-]*")


def extract_session_search_topic(text: str) -> str | None:
    """
    Extract the most likely topic keyword to search saved sessions
    for, from a message already recognized by
    `has_session_retrieval_intent()` (e.g. "Docker" from "Search
    previous sessions for Docker.", "Laravel" from "Find where I
    mentioned Laravel.").

    Returns None when no topic keyword remains after stripping the
    intent phrasing itself (e.g. "Summarize our previous
    discussions.", "Search previous sessions and introduce me.") --
    callers should fall back to the most recently updated sessions
    instead of an FTS5 query in that case, since there is no
    meaningful keyword to search for.
    """

    raw_words = _WORD_PATTERN.findall(text)
    words = [word.strip(".,!?;:'\"") for word in raw_words]
    words = [word for word in words if word]
    keywords = [word for word in words if word.lower() not in _QUERY_STOPWORDS]

    if not keywords:
        return None

    return max(keywords, key=len)
