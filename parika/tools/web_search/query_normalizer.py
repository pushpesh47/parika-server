"""
PARIKA Web Search Tool - Query Normalization

Detects and rewrites ambiguous or search-unfriendly query phrases
before dispatch to a SearchBackend (Phase 1 Item 1: "Fix Web Search
Query Generation").

The concrete problem this addresses: a query such as "current prime
minister of Japan" is unambiguous to a human, but a term-overlap-
driven search backend or ranker (see `ranking.py`) may equally match
unrelated documents about "current" in the electrical sense, because
the word "current" alone is genuinely ambiguous outside its temporal
context. Rewriting "current <role>" to "incumbent <role>" removes
the ambiguous term entirely while preserving the user's exact intent
- it never invents information the user did not supply.

Deliberately narrow and stdlib-only (`re`): this module recognizes a
small, well-defined ambiguity taxonomy inspired by ambiguous-query
research (e.g. AmbigChat, ACM UIST 2025 - temporal, geographic,
entity, and question-adverb facets), but only Phase 1's concrete
"temporal" facet (the "current <role>" pattern) is actually detected
and rewritten today; the other facets require external knowledge
(e.g. resolving which "Georgia" a query means) that a stdlib regex
cannot reliably supply without risking an incorrect rewrite, so they
are documented as future extension points rather than guessed at.

PARIKA is a generic AI Kernel, not a news, weather, or search
application (see `driver.py`'s own module docstring): this module's
transformations are domain-agnostic wording fixes, never a
topic-specific rule.
"""

from __future__ import annotations

import re

_ROLE_NOUNS: tuple[str, ...] = (
    "vice president",
    "prime minister",
    "president",
    "minister",
    "chancellor",
    "governor",
    "mayor",
    "premier",
    "king",
    "queen",
    "pope",
    "ceo",
    "chairwoman",
    "chairperson",
    "chairman",
    "secretary-general",
    "secretary general",
    "director-general",
    "director general",
    "commissioner",
    "ambassador",
    "speaker",
    "head of state",
    "head of government",
)
"""
Role/title nouns that make "current"'s temporal ("present-day
officeholder") sense unambiguous to a human when immediately
preceding one of them, but not necessarily to a term-overlap-driven
search backend or ranker, which may equally match unrelated documents
about "current" in the electrical sense. Ordered with longer, more
specific phrases first (e.g. "vice president" before "president") so
the regex alternation prefers the most specific match when phrases
overlap.
"""

_ROLE_NOUN_ALTERNATION = "|".join(re.escape(role) for role in _ROLE_NOUNS)

_CURRENT_ROLE_PATTERN = re.compile(
    rf"\bcurrent(\s+)({_ROLE_NOUN_ALTERNATION})\b",
    re.IGNORECASE,
)
"""
Matches "current" only when immediately followed by one of
`_ROLE_NOUNS` - never a bare "current" - so unrelated queries (e.g.
"current weather", "current exchange rate", "current events") are
never rewritten. Capturing groups preserve the original whitespace
and role-noun casing for the replacement in `normalize()`.
"""

_FILLER_PREFIX_PATTERN = re.compile(
    r"^(?:"
    r"what(?:'s| is| are)\s+|"
    r"who(?:'s| is)\s+|"
    r"tell me (?:about\s+)?|"
    r"please\s+|"
    r"can you (?:tell me\s+|find\s+)?|"
    r"could you (?:tell me\s+|find\s+)?|"
    r"give me\s+"
    r")+",
    re.IGNORECASE,
)
"""
Common conversational filler/interrogative prefixes that add noise
for keyword-oriented search backends without changing the user's
intent (e.g. "What is the current exchange rate for USD to INR?"
searches identically well as "the current exchange rate for USD to
INR"). Stripped unconditionally by `normalize()`, independent of
ambiguity detection - repeated (`+`) so chained fillers (e.g. "please
tell me about ...") are fully removed in one pass.
"""

_PUNCTUATION_PATTERN = re.compile(r"[?!.,;:]+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class QueryNormalizer:
    """
    Normalizes and disambiguates search query text before dispatch.

    Stateless and side-effect free: every method is a pure function
    of its argument, never a decision about which Capability or Tool
    a request targets.
    """

    def normalize(self, query: str) -> str:
        """
        Apply Phase 1's first-pass normalization: strip a leading
        conversational filler/interrogative phrase, then rewrite the
        "current <role>" ambiguity pattern when present.

        Args:
            query:
                Raw query text as supplied by the caller (typically
                the model's tool-call argument).

        Returns:
            The normalized query. A query with no filler prefix and
            no ambiguous role pattern is returned unchanged (aside
            from surrounding whitespace).
        """

        stripped = _FILLER_PREFIX_PATTERN.sub("", query.strip())
        disambiguated = _CURRENT_ROLE_PATTERN.sub(r"incumbent\1\2", stripped)
        normalized = disambiguated.strip()

        return normalized or query.strip()

    def detect_ambiguity(self, query: str) -> tuple[bool, str | None]:
        """
        Detect whether `query` contains a recognized ambiguous
        phrase.

        Args:
            query:
                Query text to inspect (typically the *original*,
                pre-normalization query).

        Returns:
            `(is_ambiguous, facet)`. `facet` is `"temporal"` when the
            "current <role>" pattern is detected - the only facet
            Phase 1 implements. Returns `(False, None)` otherwise.
            `"geographic"`, `"entity"`, and `"question_adverb"` are
            reserved facet names for future rules; this method never
            returns them today (see module docstring).
        """

        if _CURRENT_ROLE_PATTERN.search(query):
            return True, "temporal"

        return False, None

    def rewrite_for_retry(self, query: str) -> str:
        """
        Produce a second-pass, more aggressive rewrite for use only
        when the first attempt's results failed to meet the minimum
        validation confidence (see `validation.py`).

        Strips punctuation and collapses whitespace beyond what
        `normalize()` already does, giving the backend a cleaner,
        keyword-focused query without inventing new terms.

        Args:
            query:
                The query that was already attempted (normally the
                output of `normalize()`).

        Returns:
            The rewritten query. May be identical to `query` when
            there is nothing left to strip - callers should skip a
            retry entirely in that case, since re-issuing an
            identical query to a deterministic backend cannot change
            the outcome.
        """

        rewritten = _PUNCTUATION_PATTERN.sub(" ", query)
        rewritten = _WHITESPACE_PATTERN.sub(" ", rewritten).strip()

        return rewritten or query
