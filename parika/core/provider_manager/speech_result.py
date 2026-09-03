"""
PARIKA Core - ProviderManager Component

Defines the provider-independent speech result type.

`SpeechResult` is the generic analogue of a concrete speech provider's
own response (e.g. faster-whisper's segment list, or Kokoro's raw PCM
output): the normalized outcome of one speech recognition/synthesis
operation that every provider-independent layer (Modules) consumes,
with no provider-specific wire concept. The Provider selected by
Planner produces this from its own concrete engine output at the
provider boundary (`ProviderDriver.execute()` for a `SpeechRequest`),
exactly like every other `ProviderResponse` subtype (see
`GenerationResult` for the established pattern this type mirrors).

Never carries a provider's raw engine payload (e.g. faster-whisper's
segment/word timestamps, or Kokoro's internal synthesis config) -- only
the normalized outcome every caller needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .response import ProviderResponse


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechResult(ProviderResponse):
    """
    Provider-independent outcome of one speech recognition/synthesis
    operation.

    Attributes:
        text:
            Recognized text, for `SpeechOperation.SPEECH_TO_TEXT`.
            Empty for `TEXT_TO_SPEECH`.

        language_detected:
            The language the provider recognized/used, when it
            reports one (e.g. `"en"`, `"hi"`). `None` when the
            provider does not report this.

        audio_base64:
            Base64-encoded synthesized audio bytes, for
            `SpeechOperation.TEXT_TO_SPEECH`. Empty for
            `SPEECH_TO_TEXT`.

        audio_mime_type:
            IANA media type of `audio_base64` (e.g. `"audio/wav"`).
            Empty for `SPEECH_TO_TEXT`.

        sample_rate:
            Sample rate, in Hz, of `audio_base64`. `None` for
            `SPEECH_TO_TEXT`, or when the provider does not report
            one.

        duration_seconds:
            Duration, in seconds, of the input audio (`SPEECH_TO_TEXT`)
            or the synthesized audio (`TEXT_TO_SPEECH`), when the
            provider reports it. `None` when unreported.

        language_confidence:
            The provider's own confidence (0.0-1.0) in
            `language_detected`, for `SPEECH_TO_TEXT`, when the
            provider reports one -- populated only when the language
            was actually auto-detected (a caller-forced language skips
            the recognizer's own detection pass, so no confidence
            exists to report). `None`, never a fabricated value,
            whenever the provider does not report this or does not
            apply (`TEXT_TO_SPEECH`).
    """

    text: str = ""
    language_detected: str | None = None
    audio_base64: str = ""
    audio_mime_type: str = ""
    sample_rate: int | None = None
    duration_seconds: float | None = None
    language_confidence: float | None = None
