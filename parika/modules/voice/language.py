"""
PARIKA Voice Module - Language Model

Introduces the small, explicit English/Hindi language contract for
Voice, and the single, shared, mutable "current Voice language
preference" that both `SpeechToTextToolDriver` and
`TextToSpeechToolDriver` consult -- deliberately extending the
existing dynamic-output-preference principle already established by
ADR 0002 Decision 5 ("the current output preference determines
whether TTS starts, evaluated when the canonical text response
becomes available") to *which language* Voice should use, rather than
inventing a second, parallel state mechanism.

Scope (deliberately narrow, per this Module's own task-level
constraints):

- Exactly two spoken languages are supported end-to-end: English
  (`"en"`) and Hindi (`"hi"`). No broader internationalization
  framework, no Hinglish category, no free-form language strings.
- Input language (what should STT expect/detect) and output language
  (what should TTS speak) are kept distinct: `VoiceInputLanguage` adds
  `AUTO` (let the engine detect it); `VoiceOutputLanguage` adds
  `FOLLOW_INPUT` (speak whatever language was most recently
  used/detected on the input side) instead.
- `VoiceLanguagePreferenceStore` is a small, `RLock`-guarded,
  in-memory singleton -- structurally identical to
  `operation_registry.TtsOperationRegistry` (same "one focused fact,
  one shared instance, ServiceContainer-registered" shape; see that
  module's own docstring for the precedent) -- holding exactly the
  Voice-boundary language preference PARIKA currently has: no
  `LanguageManager`, no `VoiceSessionManager`, no per-user-account
  persistence (PARIKA has no such concept today), no second
  configuration system. Its *initial* value comes from `[voice]`
  configuration (`load_voice_config()`); after that it is a live,
  request-independent "current preference" a caller can read or update
  through the Voice API's settings endpoints
  (`parika.api.handlers.voice.handle_voice_get_settings`/
  `handle_voice_update_settings`) exactly as freely as a caller
  decides, independently, whether to call `POST /voice/speak` at all.

Neither `VoiceInputLanguage`/`VoiceOutputLanguage` nor this store leak
into `SpeechRequest`/`SpeechResult` (still plain `str | None`) or into
any Provider/engine adapter: those remain exactly as generic as
before. Resolution to a concrete `"en"`/`"hi"` string always happens
here, at the Voice Module boundary, before a request ever reaches a
Provider -- Core (Brain/Planner/Router/ProviderManager) remains
entirely language-agnostic, per this task's own architecture
boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from threading import RLock


class VoiceInputLanguage(StrEnum):
    """
    Requested speech-recognition language for one Voice input
    operation (`voice.speech_to_text`/`voice.respond`).

    `AUTO` lets the underlying speech-to-text engine (faster-whisper)
    detect the spoken language itself -- never a Unicode-script/
    keyword heuristic, and never a call to the chat model to guess.
    """

    AUTO = "auto"
    ENGLISH = "en"
    HINDI = "hi"


class _RemovedVoiceOutputLanguage(StrEnum):
    """
    Requested speech-synthesis language policy for one Voice output
    operation (`voice.text_to_speech`/`voice.speak`).

    `FOLLOW_INPUT` defers to whatever language was most recently
    used/detected on the *input* side (see
    `VoiceLanguagePreferenceStore.record_detected_input_language()`),
    implementing "TTS speaks whatever language the user has most
    recently been speaking/selected" without coupling input and output
    language into a single concept.
    """

    HINDI = "hi"


SUPPORTED_SPOKEN_LANGUAGES: frozenset[str] = frozenset({"en", "hi"})
"""
The only two concrete spoken-language codes PARIKA Voice actually
recognizes/synthesizes end-to-end. `"auto"` and `"follow_input"` are
*policies*, never themselves a spoken language.
"""

TTS_LANGUAGE = "hi"
"""
Used only when no other signal (explicit request, current preference,
detected input language) resolves an output language at all -- e.g.
the very first `speak` call of a session, before any input has ever
been transcribed.
"""


class VoiceLanguageError(ValueError):
    """
    Raised when a caller-supplied language string is not one of this
    Module's supported values. Callers translating this into an API
    response should report it as a client error (see
    `parika.api.schemas.voice`'s language field validators, which
    raise this from a pydantic `field_validator` so it becomes a
    normal `422 RequestValidationError`).
    """


def parse_input_language(value: str | None) -> VoiceInputLanguage:
    """
    Parse a wire-level input-language string into `VoiceInputLanguage`.

    `None`, `""`, and `"auto"` (case-insensitively) all mean `AUTO`,
    matching the pre-existing convention that omitting a language hint
    lets the engine auto-detect. Any other value must be exactly
    `"en"` or `"hi"`.

    Raises:
        VoiceLanguageError: If `value` is a non-empty string that is
            not `"auto"`, `"en"`, or `"hi"`.
    """

    if value is None:
        return VoiceInputLanguage.HINDI

    normalized = value.strip().lower()

    if not normalized or normalized == VoiceInputLanguage.AUTO.value:
        return VoiceInputLanguage.AUTO

    try:
        return VoiceInputLanguage(normalized)
    except ValueError:
        raise VoiceLanguageError(
            f"Unsupported input language '{value}'. PARIKA Voice "
            "currently supports only 'auto', 'en', or 'hi'."
        ) from None


def parse_output_language(value: str | None) -> str:
    """
    Parse a wire-level output-language string into
    `VoiceOutputLanguage`.

    `None`, `""`, and `"follow_input"` (case-insensitively) all mean
    `FOLLOW_INPUT`. Any other value must be exactly `"en"` or `"hi"`.

    Raises:
        VoiceLanguageError: If `value` is a non-empty string that is
            not `"follow_input"`, `"en"`, or `"hi"`.
    """

    if value is None:
        return TTS_LANGUAGE

    normalized = value.strip().lower()

    if not normalized:
        return TTS_LANGUAGE

    if normalized == TTS_LANGUAGE:
        return TTS_LANGUAGE

    try:
        raise ValueError
    except ValueError:
        raise VoiceLanguageError(
            f"Unsupported output language '{value}'. PARIKA Voice "
            "currently supports only 'hi'."
        ) from None


def is_supported_spoken_language(language_code: str | None) -> bool:
    """Whether `language_code` is one of the concrete `en`/`hi` codes."""

    return language_code in SUPPORTED_SPOKEN_LANGUAGES


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceLanguagePreference:
    """
    Immutable snapshot of the current Voice language preference.

    Attributes:
        input_language:
            The currently selected input-language policy
            (`auto`/`en`/`hi`).

        output_language:
            The currently selected output-language policy
            (`en`/`hi`/`follow_input`).

        last_detected_input_language:
            The most recently detected/used input language (`"en"` or
            `"hi"`), or `None` before any speech-to-text operation has
            run. Consulted only when `output_language` is
            `FOLLOW_INPUT`.
    """

    input_language: VoiceInputLanguage = VoiceInputLanguage.AUTO
    last_detected_input_language: str | None = None


class VoiceLanguagePreferenceStore:
    """
    Thread-safe holder for PARIKA's *current* Voice language
    preference -- see this module's own docstring for why this exists
    and exactly what it deliberately is not.
    """

    def __init__(self, *, default: VoiceLanguagePreference | None = None) -> None:
        self._lock = RLock()
        self._preference = default or VoiceLanguagePreference()

    def get(self) -> VoiceLanguagePreference:
        """Return the current preference snapshot."""

        with self._lock:
            return self._preference

    def set_input_language(
        self, input_language: VoiceInputLanguage
    ) -> VoiceLanguagePreference:
        """Update the current input-language policy."""

        with self._lock:
            self._preference = replace(
                self._preference, input_language=input_language
            )
            return self._preference

    def record_detected_input_language(self, language_code: str | None) -> None:
        """
        Record the most recently detected/used input language, for a
        later `FOLLOW_INPUT`-policy `speak` call to resolve against.

        Called after every `voice.speech_to_text` operation
        (explicit-language or auto-detected alike) -- see
        `driver_stt.py` -- regardless of whether that operation's
        detected language was itself supported, so an unsupported
        detection never silently freezes `FOLLOW_INPUT` on a stale
        value; it simply leaves the last *supported* detection (if
        any) or `None` in place (see `resolve_output_language()`'s own
        fallback rule).
        """

        if language_code is not None and not is_supported_spoken_language(
            language_code
        ):
            return

        with self._lock:
            self._preference = replace(
                self._preference, last_detected_input_language=language_code
            )

    def resolve_input_language(self, *, explicit: str | None) -> VoiceInputLanguage:
        """
        Resolve the input-language policy for one `speech_to_text`
        request:

        1. `explicit`, if supplied (parsed/validated).
        2. Otherwise, the current `input_language` preference.
        """

        if explicit:
            return parse_input_language(explicit)

        return self.get().input_language
