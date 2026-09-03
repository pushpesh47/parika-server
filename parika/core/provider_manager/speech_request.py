"""
PARIKA Core - ProviderManager Component

Defines the provider-independent speech request type.

`SpeechRequest` is the generic analogue of a concrete speech
provider's own engine-specific request (e.g. a faster-whisper
transcription call, or a Kokoro synthesis call): it carries only the
semantic speech intent every speech-capable provider needs -- what
operation is being requested, either input audio (speech-to-text) or
input text (text-to-speech), and optional language/voice hints -- with
no provider-specific wire concept (no model file paths, device
strings, or engine-specific parameters). Modules build this type via a
Goal's `provider_request_builder`; the Provider selected by Planner
converts it into its own concrete engine call at the provider boundary
(`ProviderDriver.execute()`), exactly like every other `ProviderRequest`
subtype (see `GenerationRequest` for the established pattern this type
mirrors).

Deliberately not an LLM request: `SpeechRequest` has no concept of a
conversation, a system prompt, or reasoning -- only a single, bounded
speech recognition/synthesis operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .request import ProviderRequest


class SpeechOperation(StrEnum):
    """
    Semantic speech operation a `SpeechRequest` represents.

    Deliberately a closed, provider-independent vocabulary of *what
    the caller wants*, not *how any specific provider does it*. A
    Provider maps each operation (together with the selected
    `ProviderModel`) to its own internal engine call.
    """

    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechRequest(ProviderRequest):
    """
    Provider-independent request for one speech recognition/synthesis
    operation.

    Attributes:
        operation:
            The semantic speech operation requested.

        audio_base64:
            Base64-encoded input audio bytes, in the same provider-
            independent shape as `ChatMessage.images`. Required for
            `SPEECH_TO_TEXT`; ignored for `TEXT_TO_SPEECH`.

        audio_mime_type:
            IANA media type hint of `audio_base64` (e.g. `"audio/wav"`),
            when known. Providers with no format-sniffing concern of
            their own may still use this to reject an unsupported
            format early; `None` means "unknown, best-effort".

        text:
            Text to synthesize into speech. Required for
            `TEXT_TO_SPEECH`; ignored for `SPEECH_TO_TEXT`.

        language:
            Optional BCP-47-ish language hint (e.g. `"en"`, `"hi"`).
            For `SPEECH_TO_TEXT`, a hint to the recognizer; `None`
            lets the provider auto-detect. For `TEXT_TO_SPEECH`, a
            hint for voice/language selection; `None` lets the
            provider choose its configured default.

        voice:
            Optional provider-specific voice/speaker identifier hint
            for `TEXT_TO_SPEECH`. Providers with no concept of
            multiple voices simply ignore it. `None` lets the
            provider choose its configured default voice.
    """

    operation: SpeechOperation
    audio_base64: str = ""
    audio_mime_type: str | None = None
    text: str = ""
    language: str | None = None
    voice: str | None = None
