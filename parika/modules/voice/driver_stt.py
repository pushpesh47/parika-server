"""
PARIKA Voice Module - Speech-to-Text ToolDriver

Implements `voice.speech_to_text`: an orchestrator ToolDriver that
obtains input audio either directly (`audio_base64`, the fast path the
Voice API uses -- see `parika.api.handlers.voice`) or, like
`generation.driver_image.ImageEditToolDriver`, through the existing
`filesystem.read` Capability (`path`, for a chat-model-initiated call
against an already-uploaded/known audio file), and delegates the
actual recognition to this Module's own Provider-backed Capability
(`voice.provider_speech_to_text`, resolved by Planner's Model
Selection Framework to whichever compatible Provider is registered --
the Local Speech Provider today). Never constructs or inspects a
faster-whisper-specific type.

Language handling (additive; see `language.py`): the requested input
language is resolved -- explicit request argument first, then the
shared `VoiceLanguagePreferenceStore`'s current `input_language`
preference -- to a concrete engine hint (`None` for `AUTO`, `"en"`/
`"hi"` otherwise) *before* the nested Provider Goal is built, so the
Provider itself never sees the `auto`/policy vocabulary, only a plain
`str | None`. The engine's own detected language is always recorded
back into the preference store (win or lose against `en`/`hi`
support) so a later `FOLLOW_INPUT`-policy `speak` call can resolve
against it -- this is the only place `voice.speech_to_text` writes to
that shared state.
"""

from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine
from .exceptions import VoiceInputInvalidError
from .language import (
    VoiceInputLanguage,
    VoiceLanguagePreferenceStore,
    is_supported_spoken_language,
)


class SpeechToTextToolDriver:
    """`ToolDriver` implementing `voice.speech_to_text`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        language_preference: VoiceLanguagePreferenceStore | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._language_preference = (
            language_preference or VoiceLanguagePreferenceStore()
        )
        self._progress = progress_reporter or NullProgressReporter(
            "voice.speech_to_text"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        audio_base64 = str(request.arguments.get("audio_base64", "")).strip()
        path = str(request.arguments.get("path", "")).strip()
        mime_type = request.arguments.get("mime_type")
        requested_language = request.arguments.get("language") or None

        self._progress.started(message="Transcribing audio...")

        if not audio_base64 and not path:
            raise VoiceInputInvalidError(
                "request.arguments must supply either 'audio_base64' "
                "or 'path'."
            )

        if not audio_base64:
            audio_base64 = engine.read_file_base64(self._brain, path)

        resolved_input_language = self._language_preference.resolve_input_language(
            explicit=str(requested_language) if requested_language else None
        )
        language_source = "explicit" if requested_language else "auto"
        engine_language_hint = (
            None
            if resolved_input_language is VoiceInputLanguage.AUTO
            else str(resolved_input_language)
        )

        result = engine.transcribe_with_provider(
            self._brain,
            self._provider_capability_id,
            audio_base64=audio_base64,
            audio_mime_type=str(mime_type) if mime_type else None,
            language=engine_language_hint,
        )

        detected_language = result.language_detected
        unsupported = bool(
            detected_language and not is_supported_spoken_language(detected_language)
        )

        if engine_language_hint is None and unsupported:
            language_source = "unsupported"

        # Record the outcome for a later FOLLOW_INPUT-policy `speak`
        # call to resolve against -- regardless of whether it was
        # itself explicit/auto/unsupported (see this module's own
        # docstring; unsupported detections are simply ignored by the
        # store, never poisoning the last *supported* value).
        self._language_preference.record_detected_input_language(detected_language)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "text": result.text,
                "language": detected_language,
                "requested_input_language": str(resolved_input_language),
                "detected_input_language": detected_language,
                "language_source": language_source,
            },
            attributes={
                "language_detected": detected_language,
                "duration_seconds": result.duration_seconds,
                "language_confidence": result.language_confidence,
                "language_supported": (
                    None if detected_language is None else not unsupported
                ),
            },
        )
