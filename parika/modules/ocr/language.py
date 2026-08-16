"""
PARIKA OCR Module - Deterministic Language Detection

Statistical language detection over already-recognized text (never a
fresh model call by itself) - see `text_tools_driver.py`'s
`ocr.detect_language`, which composes this with `ocr.extract_text`'s
own output so a caller who already has recognized text pays zero
additional cost at all.

Requires the optional `langdetect` dependency (`pyproject.toml`'s
`ocr` extra); raises `OcrDependencyUnavailableError` when it is not
installed, the same gracefully-degrading contract every other
optional-dependency module in this package follows.

`langdetect` reuses Google's own n-gram language-profile algorithm,
which is internally randomized for short/ambiguous input unless a
fixed seed is set; `DetectorFactory.seed` is pinned once, at first
use, so repeated calls on the same text always agree - a real
correctness requirement for a capability described as "deterministic".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import OcrDependencyUnavailableError

_SEEDED = False


def _require_language_detection() -> None:
    from .config import language_detection_dependency_available

    if not language_detection_dependency_available():
        raise OcrDependencyUnavailableError(
            "Language detection requires the optional 'ocr' dependency "
            "group (langdetect) to be installed."
        )


def _ensure_deterministic_seed() -> None:
    global _SEEDED

    if _SEEDED:
        return

    from langdetect.detector_factory import DetectorFactory  # type: ignore[import-untyped]

    DetectorFactory.seed = 0
    _SEEDED = True


@dataclass(frozen=True, slots=True, kw_only=True)
class LanguageCandidate:
    """One candidate language and its statistical confidence, in `[0, 1]`."""

    language: str
    confidence: float


@dataclass(frozen=True, slots=True, kw_only=True)
class LanguageDetectionResult:
    """Result of `detect_language()` - see its docstring."""

    detected: bool
    language: str | None
    confidence: float
    candidates: tuple[LanguageCandidate, ...] = field(default_factory=tuple)


def detect_language(text: str, *, max_candidates: int = 3) -> LanguageDetectionResult:
    """
    Detect the dominant language of `text` via `langdetect`'s
    statistical n-gram model - a purely deterministic computation over
    text that has already been recognized, never a new model call.

    Returns `detected=False` (never raises) for empty/whitespace-only
    or otherwise too-short-to-classify text, since that is an ordinary,
    expected outcome, not a failure.
    """

    _require_language_detection()
    _ensure_deterministic_seed()

    from langdetect import detect_langs  # type: ignore[import-untyped]
    from langdetect.lang_detect_exception import (  # type: ignore[import-untyped]
        LangDetectException,
    )

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
