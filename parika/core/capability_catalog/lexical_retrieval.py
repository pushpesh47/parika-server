"""
Capability Catalog - Lexical Retrieval stage.

Scores each candidate capability against the current turn's text using
only the capability's own generic discovery metadata: `name`,
`description`, `tags`, `aliases`, `keywords`, and `examples`. This is
deliberately NOT regex/pattern-based intent routing (that framework
was removed from PARIKA and must not be reintroduced -- see
`docs/architecture/PARIKA_*` decision log): it is a field-weighted,
IDF-weighted token-overlap score computed generically from data the
capability itself supplies, with no capability-specific branching
anywhere in this module.

Default retrieval strategy: **field-weighted TF-IDF-style scoring**
(`_field_weighted_idf_scores()`), computed fresh from `definitions` on
every `score_candidates()` call -- never a fixed/precomputed index,
since the candidate batch (and therefore corpus statistics) legitimately
differs turn to turn. Two ideas are combined, both standard information
retrieval technique, neither capability-specific:

- **IDF (inverse document frequency)**: a query token that appears in
  many candidates' discovery text (e.g. an ordinary implementation
  word like "current" that happens to appear in an unrelated
  capability's description, such as "...using the current exchange
  rate") contributes proportionally less to that capability's score
  than a token that appears in few or none (e.g. "weather", "pdf").
  This is what keeps a generic qualifier word in the query from
  dragging in every capability whose description happens to share it,
  without ever hardcoding which words are "common" -- document
  frequency is measured directly from *this turn's own candidate set*.
- **Field weighting**: a match in a capability's own `name` or
  `aliases` (its primary identity) counts for more than the same word
  merely appearing somewhere in its free-form `description` or
  `examples`; `tags`/`keywords` (curated, deliberately-set retrieval
  metadata) sit in between. This is what lets a query like "current
  weather" correctly favor `weather.current` (whose *name* is literally
  "Weather Current") over a capability that only happens to mention
  "current" once in passing prose.

Every score is clamped to the canonical `[0.0, 1.0]` range described
below.

Extensibility: `LexicalScorer` is a `Protocol`, and `score_candidates()`
falls back to it whenever a caller supplies an explicit `scorer`
override, so an entirely different lexical strategy can still be
substituted without changing the Capability Catalog's public API (see
`TokenOverlapScorer` for a simpler, corpus-independent alternative kept
for exactly this purpose). See `semantic_retrieval.py` for the parallel
extension point reserved for future semantic/embedding-based retrieval.
"""

from __future__ import annotations

import math
import re
from typing import Protocol

from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

_MAX_SCORE = 1.0
"""
Upper bound every scorer in this module clamps its score to. Keeping
every score source in the same canonical `[0.0, 1.0]` range is what
lets `CapabilityCatalog` combine lexical and (in future) semantic
scores by simple addition without one source being able to silently
dominate the other purely due to differing scales.
"""

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "so", "of",
        "in", "on", "at", "to", "for", "with", "about", "as", "by",
        "from", "into", "onto", "off", "out", "up", "down", "over",
        "under", "between", "among", "through", "during", "before",
        "after", "above", "below", "across", "around", "against",
        "without", "within", "along", "upon", "toward", "towards",
        "is", "are", "was", "were", "be", "been", "being", "am",
        "i", "you", "he", "she", "it", "we", "they", "me", "him",
        "her", "us", "them", "my", "your", "his", "its", "our",
        "their", "this", "that", "these", "those", "what", "which",
        "who", "whom", "whose", "when", "where", "why", "how",
        "do", "does", "did", "doing", "can", "could", "will",
        "would", "should", "shall", "may", "might", "must",
        "not", "no", "yes", "please", "just", "again", "there",
        "here", "than", "too", "very", "s", "t", "d", "ll", "m",
        "re", "ve",
    }
)
"""
Generic English function words excluded from every discovery/query
tokenization. This is standard information-retrieval stopword removal
-- not domain routing, not capability-specific knowledge, and never a
regex-based intent match: it purely reduces noise from words that
carry no topical signal (e.g. "who are you?" should not spuriously
overlap with an unrelated capability's description merely because both
happen to contain the word "are"). Kept as a fixed, generic list; not
configurable per capability. Corpus-level IDF weighting (see the module
docstring) further reduces noise from ordinary, non-function words that
happen to be common within a specific batch of candidates -- this list
only ever needs to cover *universal* English function words.
"""

_FIELD_WEIGHT_IDENTITY = 3.0
"""
Weight applied to a token found in a capability's `name` or `aliases`
-- its own stated identity. The strongest possible discovery signal: a
capability's name is what it calls itself, not incidental prose.
"""

_FIELD_WEIGHT_CURATED = 2.0
"""
Weight applied to a token found in a capability's `tags` or
`keywords` -- metadata deliberately curated for categorization/
retrieval, stronger than free-form prose but not as strong as the
capability's own name.
"""

_FIELD_WEIGHT_PROSE = 1.0
"""
Weight applied to a token found only in a capability's `description`
or `examples` -- free-form prose, the most likely place for an
ordinary, non-discriminating word to appear incidentally (e.g. "...
using the *current* exchange rate").
"""

_MAX_FIELD_WEIGHT = _FIELD_WEIGHT_IDENTITY
"""
The highest weight any field can contribute, used to normalize
`_field_weighted_idf_scores()`'s output back into `[0.0, 1.0]` (see
that function).
"""


def _tokenize(text: str) -> frozenset[str]:
    """
    Split `text` into a lowercase set of normalized alphanumeric
    tokens, with common English stopwords removed (see `_STOPWORDS`)
    and simple plural forms singularized (see `_singularize()`).
    """

    return frozenset(
        _singularize(token)
        for token in _TOKEN_PATTERN.findall(text.lower())
        if token not in _STOPWORDS
    )


def _singularize(token: str) -> str:
    """
    Lightweight, generic English plural-to-singular normalization
    (e.g. "emails" -> "email", "capabilities" -> "capability",
    "matches" -> "match") so a query using one inflected form still
    matches a capability's discovery text using another. Deliberately
    conservative -- never verb-tense normalization, and never applied
    to short words -- to avoid mangling unrelated tokens; missing an
    inflection only costs a potential match, never introduces a wrong
    one. This is standard, language-general text normalization, not
    capability-specific knowledge.
    """

    if len(token) <= 4:
        return token

    if token.endswith("ies"):
        return token[:-3] + "y"

    if token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]

    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]

    return token


def _weighted_discovery_tokens(
    definition: CapabilityDefinition,
) -> dict[str, float]:
    """
    Collect every token from `definition`'s own generic discovery
    metadata, weighted by which field it was found in (see the module
    docstring's "Field weighting" explanation). A token appearing in
    more than one field keeps the highest weight among them.
    """

    weighted: dict[str, float] = {}

    def _add(tokens: frozenset[str], weight: float) -> None:
        for token in tokens:
            if weighted.get(token, 0.0) < weight:
                weighted[token] = weight

    _add(_tokenize(definition.name), _FIELD_WEIGHT_IDENTITY)

    for alias in definition.aliases:
        _add(_tokenize(alias), _FIELD_WEIGHT_IDENTITY)

    for tag in definition.tags:
        _add(_tokenize(tag), _FIELD_WEIGHT_CURATED)

    for keyword in definition.keywords:
        _add(_tokenize(keyword), _FIELD_WEIGHT_CURATED)

    _add(_tokenize(definition.description), _FIELD_WEIGHT_PROSE)

    for example in definition.examples:
        _add(_tokenize(example), _FIELD_WEIGHT_PROSE)

    return weighted


def _discovery_tokens(definition: CapabilityDefinition) -> frozenset[str]:
    """
    Collect every token from `definition`'s own generic discovery
    metadata, ignoring field weighting. Used by `TokenOverlapScorer`
    (a simpler, corpus-independent alternative to the default
    field-weighted-IDF scoring; see the module docstring) and by
    anything that only needs to know *whether* a token appears at all.
    """

    return frozenset(_weighted_discovery_tokens(definition))


def _document_frequencies(
    definitions: tuple[CapabilityDefinition, ...],
) -> dict[str, int]:
    """
    Count how many candidates' discovery text contains each token,
    across every field, scoped to exactly this batch of `definitions`
    -- never the full `CapabilityRegistry`, so document frequency
    always reflects what is actually being considered this turn.
    """

    frequencies: dict[str, int] = {}

    for definition in definitions:
        for token in _weighted_discovery_tokens(definition):
            frequencies[token] = frequencies.get(token, 0) + 1

    return frequencies


def _inverse_document_frequency(
    token: str, *, document_frequency: dict[str, int], corpus_size: int
) -> float:
    """
    Smoothed inverse document frequency for `token`: higher for a
    token that appears in fewer candidates, lower for one shared by
    many -- always positive, so a token entirely absent from the
    corpus still contributes (it simply cannot be matched by any
    candidate either, so it only affects normalization, never causes a
    false match).
    """

    frequency = document_frequency.get(token, 0)

    return math.log((corpus_size + 1) / (frequency + 1)) + 1.0


def _field_weighted_idf_scores(
    definitions: tuple[CapabilityDefinition, ...],
    query_tokens: frozenset[str],
) -> dict[str, float]:
    """
    Default lexical scoring strategy: field-weighted, IDF-weighted
    token overlap (see the module docstring for the full rationale).

    For each candidate, the score is the fraction of the query's total
    IDF-weighted "mass" that candidate's own discovery text accounts
    for, at whichever field weight its matching tokens were found in
    -- normalized so the theoretical maximum (every query token
    matched at the highest field weight) is exactly `1.0`.
    """

    if not query_tokens or not definitions:
        return {definition.id: 0.0 for definition in definitions}

    document_frequency = _document_frequencies(definitions)
    corpus_size = len(definitions)

    query_token_idf = {
        token: _inverse_document_frequency(
            token, document_frequency=document_frequency, corpus_size=corpus_size
        )
        for token in query_tokens
    }
    query_idf_total = sum(query_token_idf.values())

    if query_idf_total <= 0.0:
        return {definition.id: 0.0 for definition in definitions}

    denominator = _MAX_FIELD_WEIGHT * query_idf_total

    scores: dict[str, float] = {}

    for definition in definitions:
        weighted_tokens = _weighted_discovery_tokens(definition)

        numerator = sum(
            query_token_idf[token] * weighted_tokens[token]
            for token in query_tokens
            if token in weighted_tokens
        )

        scores[definition.id] = min(numerator / denominator, _MAX_SCORE)

    return scores


class LexicalScorer(Protocol):
    """
    Strategy for scoring one capability's lexical relevance to a
    turn's text. Implementations must be pure and side-effect free.

    Note this per-capability interface cannot, by itself, express a
    corpus-aware strategy like the default field-weighted-IDF scoring
    (`_field_weighted_idf_scores()`), since IDF fundamentally needs
    every candidate's discovery text to compute document frequency.
    `score_candidates()` therefore only calls a `LexicalScorer` when
    one is explicitly supplied as an override; the corpus-aware default
    is applied directly otherwise. A custom corpus-aware strategy can
    still be substituted by passing a different `score_candidates`-
    compatible callable at the `CapabilityCatalog` level if ever
    needed -- this `Protocol` remains for simpler, self-contained
    strategies (see `TokenOverlapScorer`).
    """

    def score(
        self, definition: CapabilityDefinition, *, query_tokens: frozenset[str]
    ) -> float:
        """
        Return a relevance score for `definition` given
        `query_tokens`, in the canonical `[0.0, 1.0]` range shared by
        every score source in the Capability Catalog (see
        `semantic_retrieval.SemanticScorer` for the same contract on
        the future semantic side). Higher is more relevant; 0.0 means
        "no lexical signal found" (never an error).
        """

        ...


class TokenOverlapScorer:
    """
    Simple, corpus-independent `LexicalScorer`: scores by the fraction
    of a capability's own discovery tokens that also appear in the
    query, weighted slightly toward capabilities with a larger
    absolute overlap so that a capability with many matching tokens
    outranks one with a single incidental match.

    This is *not* the Capability Catalog's default scoring strategy
    (`score_candidates()` uses the field-weighted-IDF approach
    described in the module docstring unless a `scorer` override is
    supplied) -- it is kept as a simple, explicit, pluggable
    alternative for callers who want scoring with no dependency on
    corpus-wide statistics (e.g. scoring a single capability in
    isolation).

    The result is always clamped to `[0.0, 1.0]` (see `_MAX_SCORE`) --
    not merely "non-negative" -- so lexical scores are directly
    comparable to, and combinable with, any other `[0.0, 1.0]`-bounded
    score source (e.g. a future `SemanticScorer`; see
    `semantic_retrieval.py`) without a separate renormalization step.
    """

    def score(
        self, definition: CapabilityDefinition, *, query_tokens: frozenset[str]
    ) -> float:
        if not query_tokens:
            return 0.0

        discovery_tokens = _discovery_tokens(definition)

        if not discovery_tokens:
            return 0.0

        overlap = discovery_tokens & query_tokens

        if not overlap:
            return 0.0

        coverage = len(overlap) / len(discovery_tokens)
        absolute_overlap_bonus = len(overlap) * 0.01

        return min(coverage + absolute_overlap_bonus, _MAX_SCORE)


def score_candidates(
    definitions: tuple[CapabilityDefinition, ...],
    *,
    text: str,
    scorer: LexicalScorer | None = None,
) -> dict[str, float]:
    """
    Score every candidate capability's lexical relevance to `text`.

    Args:
        definitions:
            Candidate capabilities to score.

        text:
            The current turn's message text.

        scorer:
            Optional `LexicalScorer` override. When omitted (the
            default), scoring uses the corpus-aware field-weighted-IDF
            strategy (`_field_weighted_idf_scores()`, see the module
            docstring) rather than `TokenOverlapScorer`, since that
            strategy needs every candidate's discovery text at once
            and cannot be expressed through the per-capability
            `LexicalScorer` `Protocol`.

    Returns:
        A mapping of capability id to lexical score in `[0.0, 1.0]`.
        A score of 0.0 means no lexical signal was found for that
        capability -- ranking still preserves it (see
        `capability_ranking.py`), so an unscored capability is never
        silently dropped by this stage alone.
    """

    query_tokens = _tokenize(text)

    if scorer is not None:
        return {
            definition.id: scorer.score(definition, query_tokens=query_tokens)
            for definition in definitions
        }

    return _field_weighted_idf_scores(definitions, query_tokens)
