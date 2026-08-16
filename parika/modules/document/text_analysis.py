"""
PARIKA Document Module - Deterministic Text Analysis

Every algorithm here is pure, deterministic, and never calls a
Provider model -- the "local processing first" half of this Module's
Analysis Capability family (`document.search`, `document.detect_language`,
`document.extract_keywords`, `document.extract_dates`,
`document.extract_contacts`, `document.detect_duplicates`). The other
half of that family (summarize, answer_question, compare_documents,
classify, detect_document_type, extract_entities, extract_action_items,
extract_timeline, translate) genuinely requires semantic reasoning and
is implemented in `driver_analysis.py` instead, via
`engine.analyze_content()`.

`detect_language()` reuses the same base `langdetect` dependency
(`pyproject.toml`) `parika/modules/ocr/language.py` already uses for
`ocr.detect_language`, with its own small, independent wrapper here --
language detection over plain text is a generic NLP utility, not OCR
logic, so this is deliberately not a cross-Module import of an OCR
implementation detail.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

_SEEDED = False

_STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all am an and any are aren't as at be
    because been before being below between both but by can't cannot could
    couldn't did didn't do does doesn't doing don't down during each few for
    from further had hadn't has hasn't have haven't having he he'd he'll
    he's her here here's hers herself him himself his how how's i i'd i'll
    i'm i've if in into is isn't it it's its itself let's me more most
    mustn't my myself no nor not of off on once only or other ought our
    ours ourselves out over own same shan't she she'd she'll she's should
    shouldn't so some such than that that's the their theirs them
    themselves then there there's these they they'd they'll they're
    they've this those through to too under until up very was wasn't we
    we'd we'll we're we've were weren't what what's when when's where
    where's which while who who's whom why why's with won't would
    wouldn't you you'd you'll you're you've your yours yourself
    yourselves this will can may also within upon into onto
    """.split()
)

_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")
_PHONE_PATTERN = re.compile(
    r"(?<!\w)(\+?\d{1,3}[\s.\-]?)?(\(?\d{2,4}\)?[\s.\-]?){2,4}\d{3,4}(?!\w)"
)

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO: 2024-01-05
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),  # 01/05/2024
    re.compile(r"\b\d{1,2}-\d{1,2}-\d{2,4}\b"),  # 01-05-2024
    re.compile(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
        re.IGNORECASE,
    ),  # January 5, 2024 / Jan 5th 2024
    re.compile(
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{4}\b",
        re.IGNORECASE,
    ),  # 5 January 2024
)

_REFERENCE_SECTION_PATTERN = re.compile(
    r"(?im)^\s*(references|bibliography|works cited)\s*$"
)
_REFERENCE_ENTRY_PATTERN = re.compile(
    r"(?m)^\s*(?:\[\d+\]|\(\d+\)|\d{1,3}[.)])\s+\S.*$"
)
_DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[^\s,;]+", re.IGNORECASE)


def tokenize_words(text: str) -> list[str]:
    """Lowercase, alphabetic-only word tokenization. Pure, deterministic."""

    return [match.group(0).lower() for match in _WORD_PATTERN.finditer(text)]


def extract_keywords(text: str, *, max_keywords: int = 15) -> list[dict[str, object]]:
    """
    Rank the document's most frequent non-stopword terms -- a simple,
    deterministic term-frequency heuristic (no external NLP model),
    following the spec's own "never invoke an LLM if deterministic
    extraction is sufficient" guidance.
    """

    counts = Counter(
        word for word in tokenize_words(text)
        if word not in _STOPWORDS and len(word) > 2
    )

    return [
        {"keyword": word, "count": count}
        for word, count in counts.most_common(max_keywords)
    ]


def extract_dates(text: str) -> list[str]:
    """Regex-based date-mention extraction, in first-seen order, deduplicated."""

    found: list[str] = []
    seen: set[str] = set()

    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)

            if value not in seen:
                seen.add(value)
                found.append(value)

    return found


def extract_contacts(text: str) -> dict[str, list[str]]:
    """
    Regex-based contact-detail extraction: email addresses, URLs, and
    phone numbers. Phone-number matching is necessarily heuristic
    (there is no universal format) -- short numeric runs that are
    plausibly not phone numbers (e.g. bare page numbers) are filtered
    by requiring at least 7 digits total.
    """

    emails = _dedupe(_EMAIL_PATTERN.findall(text))
    urls = _dedupe(
        url.rstrip(".,;:!?)") for url in _URL_PATTERN.findall(text)
    )

    phone_numbers: list[str] = []
    seen_phones: set[str] = set()

    for match in _PHONE_PATTERN.finditer(text):
        candidate = match.group(0).strip()
        digits = re.sub(r"\D", "", candidate)

        if len(digits) < 7 or candidate in seen_phones:
            continue

        seen_phones.add(candidate)
        phone_numbers.append(candidate)

    return {"emails": emails, "urls": urls, "phone_numbers": phone_numbers}


def extract_references(text: str, *, max_candidates: int = 200) -> list[str]:
    """
    Heuristic, deterministic bibliography/citation-entry extraction:
    prefer numbered/lettered entries found after a "References"/
    "Bibliography"/"Works Cited" heading, if one exists; otherwise
    fall back to scanning the whole document for the same numbered-
    entry shape, plus any bare DOI found anywhere.
    """

    section_match = _REFERENCE_SECTION_PATTERN.search(text)
    search_space = text[section_match.end() :] if section_match else text

    entries = [
        match.group(0).strip()
        for match in _REFERENCE_ENTRY_PATTERN.finditer(search_space)
    ]

    if not entries:
        entries = [f"DOI: {doi}" for doi in _dedupe(_DOI_PATTERN.findall(search_space))]

    return entries[:max_candidates]


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchMatch:
    """One `document.search` match."""

    offset: int
    line: int
    context: str


def search_text(
    text: str,
    query: str,
    *,
    case_sensitive: bool = False,
    use_regex: bool = False,
    context_chars: int = 80,
    max_results: int = 50,
) -> list[SearchMatch]:
    """
    Deterministic substring/regex search over already-extracted
    document text -- no semantic reasoning is needed to find literal
    or pattern occurrences, so no Provider model is ever called.
    """

    if not query:
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(query if use_regex else re.escape(query), flags)

    matches: list[SearchMatch] = []

    for match in pattern.finditer(text):
        if len(matches) >= max_results:
            break

        start = max(0, match.start() - context_chars)
        end = min(len(text), match.end() + context_chars)
        line_number = text.count("\n", 0, match.start()) + 1

        matches.append(
            SearchMatch(
                offset=match.start(),
                line=line_number,
                context=text[start:end].strip(),
            )
        )

    return matches


@dataclass(frozen=True, slots=True, kw_only=True)
class LanguageCandidate:
    language: str
    confidence: float


@dataclass(frozen=True, slots=True, kw_only=True)
class LanguageDetectionResult:
    detected: bool
    language: str | None
    confidence: float
    candidates: tuple[LanguageCandidate, ...] = field(default_factory=tuple)


def detect_language(text: str, *, max_candidates: int = 3) -> LanguageDetectionResult:
    """
    Detect the dominant language of already-extracted document text
    via `langdetect`'s statistical n-gram model -- a purely
    deterministic computation, never a model call. Returns
    `detected=False` (never raises) for empty/too-short-to-classify
    text or when `langdetect` is not installed.
    """

    import importlib.util

    if importlib.util.find_spec("langdetect") is None:
        return LanguageDetectionResult(detected=False, language=None, confidence=0.0)

    global _SEEDED

    from langdetect import detect_langs  # type: ignore[import-untyped]
    from langdetect.lang_detect_exception import (  # type: ignore[import-untyped]
        LangDetectException,
    )

    if not _SEEDED:
        from langdetect.detector_factory import (  # type: ignore[import-untyped]
            DetectorFactory,
        )

        DetectorFactory.seed = 0
        _SEEDED = True

    stripped = text.strip()

    if not stripped:
        return LanguageDetectionResult(detected=False, language=None, confidence=0.0)

    try:
        ranked = detect_langs(stripped)
    except LangDetectException:
        return LanguageDetectionResult(detected=False, language=None, confidence=0.0)

    if not ranked:
        return LanguageDetectionResult(detected=False, language=None, confidence=0.0)

    candidates = tuple(
        LanguageCandidate(language=entry.lang, confidence=round(entry.prob, 4))
        for entry in ranked[:max_candidates]
    )

    return LanguageDetectionResult(
        detected=True,
        language=candidates[0].language,
        confidence=candidates[0].confidence,
        candidates=candidates,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DuplicateComparisonResult:
    """Result of `detect_duplicates_pair()`."""

    identical: bool
    similarity: float
    """Jaccard similarity, in `[0, 1]`, over normalized word sets."""


def normalized_content_hash(text: str) -> str:
    """
    Stable content hash over whitespace-normalized, lowercased text --
    two documents whose meaningful content is byte-identical after
    normalization hash identically regardless of formatting/whitespace
    differences.
    """

    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def detect_duplicates_pair(text_a: str, text_b: str) -> DuplicateComparisonResult:
    """
    Deterministic near-duplicate detection between two documents'
    extracted text: exact match via `normalized_content_hash()`, plus
    a Jaccard word-set similarity score for partial overlap -- no
    semantic reasoning is required to detect duplication, so no
    Provider model is ever called.
    """

    hash_a, hash_b = normalized_content_hash(text_a), normalized_content_hash(text_b)

    if hash_a == hash_b:
        return DuplicateComparisonResult(identical=True, similarity=1.0)

    words_a, words_b = set(tokenize_words(text_a)), set(tokenize_words(text_b))

    if not words_a and not words_b:
        return DuplicateComparisonResult(identical=True, similarity=1.0)

    union = words_a | words_b
    similarity = len(words_a & words_b) / len(union) if union else 0.0

    return DuplicateComparisonResult(identical=False, similarity=round(similarity, 4))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)

    return result
