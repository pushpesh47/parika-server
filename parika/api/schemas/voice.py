"""
PARIKA API - Voice Schemas

Wire-format request/response for the Voice API
(`POST /api/v1/voice/transcribe`, `POST /api/v1/voice/respond`,
`POST /api/v1/voice/speak`, `POST /api/v1/voice/speak/{operation_id}
/stop`, `GET`/`PUT /api/v1/voice/settings`).

Clients never see, and these schemas never mention, `faster-whisper`,
`Kokoro`, a model path, a device, or any other server-side speech
engine implementation detail (see this Module's own architecture
documentation, "Client Contract").

Language fields (additive; see `parika.modules.voice.language`) are
validated here, at the API boundary, using the exact same
`parse_input_language()`/`parse_output_language()` PARIKA Core itself
uses -- an unsupported value (anything other than `auto`/`en`/`hi` for
input, `follow_input`/`en`/`hi` for output) is rejected as a normal
`422 RequestValidationError`, per `parika.api.errors`' centralized
error-mapping table, rather than silently accepted and only failing
deep inside the Voice Module.
"""

from __future__ import annotations

from pydantic import field_validator

from parika.modules.voice.language import (
    VoiceLanguageError,
    parse_input_language,
    parse_output_language,
)

from .common import ApiModel


def _checked_input_language(value: str | None) -> str | None:
    """
    Shared body for every `@field_validator` below validating an
    *input*-language field: accepts `None`/`"auto"`/`"en"`/`"hi"`
    (case-insensitively), raising `ValueError` (which pydantic turns
    into a normal field validation error) for anything else.
    """

    if value is None:
        return None

    try:
        parse_input_language(value)
    except VoiceLanguageError as ex:
        raise ValueError(str(ex)) from ex

    return value


def _checked_output_language(value: str | None) -> str | None:
    """
    Shared body for every `@field_validator` below validating an
    *output*-language field: accepts `None`/`"follow_input"`/`"en"`/
    `"hi"` (case-insensitively), raising `ValueError` for anything
    else.
    """

    if value is None:
        return None

    try:
        parse_output_language(value)
    except VoiceLanguageError as ex:
        raise ValueError(str(ex)) from ex

    return value


class VoiceTranscribeRequestBody(ApiModel):
    audio_base64: str
    mime_type: str | None = None
    language: str | None = None  # input language: "auto" (default), "en", or "hi"

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str | None) -> str | None:
        return _checked_input_language(value)


class VoiceTranscribeResponseBody(ApiModel):
    text: str
    # Detected/used language -- kept for backward compatibility;
    # equivalent to `detected_input_language` below.
    language: str | None = None
    requested_input_language: str | None = None
    detected_input_language: str | None = None
    language_source: str | None = None  # "explicit", "auto", or "unsupported"


class VoiceRespondRequestBody(ApiModel):
    audio_base64: str
    mime_type: str | None = None
    language: str | None = None  # input language: "auto" (default), "en", or "hi"
    session_id: str | None = None

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str | None) -> str | None:
        return _checked_input_language(value)


class VoiceRespondResponseBody(ApiModel):
    """
    Mirrors `ChatResponseBody` exactly, plus `transcript` -- the text
    `voice.speech_to_text` produced and then submitted through the
    exact same path a typed `ChatRequestBody` uses. Never includes
    synthesized audio: text-to-speech remains a fully independent,
    caller-initiated `POST /api/v1/voice/speak` call (see
    `docs/architecture/adr/0002-voice-capability.md`'s "why respond
    never auto-speaks" decision).
    """

    session_id: str
    succeeded: bool
    transcript: str
    message: str | None = None
    error_message: str | None = None
    detected_input_language: str | None = None
    language_source: str | None = None


class VoiceSpeakRequestBody(ApiModel):
    text: str
    voice: str | None = None
    # Explicit output-language override: "en" or "hi". Omit to use
    # the current output-language preference.
    language: str | None = None
    operation_id: str | None = None

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str | None) -> str | None:
        return _checked_output_language(value)


class VoiceSpeakResponseBody(ApiModel):
    operation_id: str
    audio_base64: str
    mime_type: str
    sample_rate: int
    cancelled: bool
    # The concrete language ("en"/"hi") actually used to select the
    # Kokoro voice.
    output_language: str | None = None


class VoiceStopSpeakingResponseBody(ApiModel):
    operation_id: str
    stopped: bool


class VoiceSettingsResponseBody(ApiModel):
    """
    Current Voice language preference plus a small, non-sensitive
    availability summary -- the server-side, authoritative state a
    Web/CLI client renders (Section 26's "Client Contract"): the
    client never determines input/output language itself.
    """

    input_language: str  # "auto", "en", or "hi"
    output_language: str  # "en", "hi", or "follow_input"
    last_detected_input_language: str | None = None
    english_voice_configured: bool
    hindi_voice_configured: bool
    stt_available: bool
    tts_available: bool


class VoiceSettingsUpdateRequestBody(ApiModel):
    """
    Partial update: an omitted field leaves that preference
    unchanged.
    """

    input_language: str | None = None
    output_language: str | None = None

    @field_validator("input_language")
    @classmethod
    def _validate_input_language(cls, value: str | None) -> str | None:
        return _checked_input_language(value)

    @field_validator("output_language")
    @classmethod
    def _validate_output_language(cls, value: str | None) -> str | None:
        return _checked_output_language(value)
