"""
PARIKA API - Voice Handler

Translates Voice API requests into calls against already-existing
Core/Interface machinery -- never a second reasoning pipeline:

- `handle_voice_transcribe`: calls `voice.speech_to_text`'s Tool
  directly through `ToolManager.execute()`. Pure `audio -> text`.

- `handle_voice_respond`: calls `voice.speech_to_text`'s Tool for the
  transcript, then delegates to the *exact same*
  `parika.api.handlers.chat.handle_chat()` every typed
  `POST /api/v1/chat` request already uses -- proving the same
  text-processing path serves both typed and voice requests, per this
  Module's architecture requirement. Never triggers text-to-speech
  itself (see `handle_voice_speak`).

- `handle_voice_speak`: calls `voice.text_to_speech`'s Tool directly
  through `ToolManager.execute()`. A fully independent operation from
  `handle_voice_respond`/`handle_chat` -- the canonical text response
  already exists by the time a caller decides to call this.

- `handle_voice_stop_speaking`: cancels an in-progress `speak`
  operation via the shared `TtsOperationRegistry` (read from
  `ServiceContainer`, per Section 15's dependency-injection
  requirement) -- never touches `ToolManager`/`ProgressReporter`'s
  execution-lifecycle guard, never affects any PARIKA request's
  completed text response.

This handler never constructs a `Goal`/`BrainRequest` itself and never
calls `Brain`/`Planner` directly -- see `parika/api/handlers/__init__.py`
for the full orchestration/translation-only rule every handler in this
package follows.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator
from uuid import uuid4

from parika.core.tool_manager.request import ToolRequest
from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore
from parika.modules.voice.capability_ids import (
    SPEECH_TO_TEXT_TOOL_ID,
    TEXT_TO_SPEECH_TOOL_ID,
    TEXT_TO_SPEECH_CAPABILITY_ID,
)
from parika.modules.voice.language import VoiceLanguagePreferenceStore
from parika.modules.voice.module_driver import VoiceModuleDriver
from parika.modules.voice.operation_registry import TtsOperationRegistry
from parika.providers.local_speech.config import load_local_speech_config

from ..requests import (
    ChatRequest,
    VoiceGetSettingsRequest,
    VoiceRespondRequest,
    VoiceSpeakRequest,
    VoiceStopSpeakingRequest,
    VoiceTranscribeRequest,
    VoiceUpdateSettingsRequest,
)
from .chat import handle_chat


def handle_voice_transcribe(
    runtime: ParikaRuntime, request: VoiceTranscribeRequest
) -> dict[str, Any]:
    """
    Transcribe audio into text. Pure `audio -> text`; never enters the
    text pipeline.
    """

    response = runtime.tool_manager.execute(
        SPEECH_TO_TEXT_TOOL_ID,
        ToolRequest(
            arguments={
                "audio_base64": request.audio_base64,
                "mime_type": request.mime_type,
                "language": request.language,
            }
        ),
    )

    return {
        "text": response.result.get("text", ""),
        "language": response.result.get("language"),
        "requested_input_language": response.result.get(
            "requested_input_language"
        ),
        "detected_input_language": response.result.get(
            "detected_input_language"
        ),
        "language_source": response.result.get("language_source"),
    }


def handle_voice_respond(
    runtime: ParikaRuntime,
    session_store: PostgreSQLSessionStore,
    request: VoiceRespondRequest,
) -> dict[str, Any]:
    """
    Transcribe audio, then submit the resulting text through the
    exact same path `handle_chat()` already uses for a typed request.

    Deliberately never synthesizes speech for the reply -- see this
    module's own docstring.
    """

    transcription = handle_voice_transcribe(
        runtime,
        VoiceTranscribeRequest(
            audio_base64=request.audio_base64,
            mime_type=request.mime_type,
            language=request.language,
        ),
    )
    transcript = str(transcription["text"])

    chat_result = handle_chat(
        runtime,
        session_store,
        ChatRequest(text=transcript, session_id=request.session_id),
    )

    return {
        **chat_result,
        "transcript": transcript,
        "detected_input_language": transcription.get("detected_input_language"),
        "language_source": transcription.get("language_source"),
    }


def handle_voice_speak(
    runtime: ParikaRuntime, request: VoiceSpeakRequest
) -> dict[str, Any]:
    """
    Synthesize speech for already-known text. Fully independent of
    any PARIKA request/response -- see this module's own docstring.
    """

    response = runtime.tool_manager.execute(
        TEXT_TO_SPEECH_TOOL_ID,
        ToolRequest(
            arguments={
                "text": request.text,
                "voice": request.voice,
                "language": request.language,
                "operation_id": request.operation_id,
            }
        ),
    )

    result = dict(response.result)
    result["output_language"] = result.get("language")

    return result


def handle_voice_stop_speaking(
    runtime: ParikaRuntime, request: VoiceStopSpeakingRequest
) -> dict[str, Any]:
    """
    Cancel an in-progress `speak` operation.

    Never raises for an unknown/already-finished `operation_id`;
    `stopped=False` simply reports that there was nothing left to
    cancel, matching Section 10's requirement that stopping TTS never
    causes any request to fail.
    """

    operation_registry = runtime.service_container.get(TtsOperationRegistry)
    stopped = operation_registry.cancel(request.operation_id)

    return {"operation_id": request.operation_id, "stopped": stopped}


def _voice_availability(runtime: ParikaRuntime) -> tuple[bool, bool, bool, bool]:
    """
    `(kokoro_voice_configured, stt_available,
    tts_available)`, read from the Local Speech Provider's own
    configuration and registered models -- never a second source of
    truth for what `[providers.local_speech]` already declares.
    """

    local_speech_config = load_local_speech_config(runtime.configuration)
    kokoro_voice_configured = bool(
        local_speech_config.tts_kokoro_model_path and local_speech_config.tts_kokoro_voices_path
    )

    stt_available = False
    tts_available = False

    for provider in runtime.provider_manager.get_all():
        if provider.id != "provider.local_speech":
            continue

        for model in provider.models:
            if "speech_to_text" in model.specializations:
                stt_available = True
            if "text_to_speech" in model.specializations:
                tts_available = True

    return (
        kokoro_voice_configured,
        kokoro_voice_configured,
        stt_available,
        tts_available,
    )


def handle_voice_get_settings(
    runtime: ParikaRuntime, request: VoiceGetSettingsRequest | None
) -> dict[str, Any]:
    """
    Report the current Voice language preference plus a small
    availability summary -- the authoritative, server-side state a
    Web/CLI client renders (see `parika.modules.voice.language`'s own
    docstring: the client never determines input/output language
    itself).
    """

    preference_store = runtime.service_container.get(VoiceLanguagePreferenceStore)
    preference = preference_store.get()
    (
        english_voice_configured,
        hindi_voice_configured,
        stt_available,
        tts_available,
    ) = _voice_availability(runtime)

    return {
        "input_language": str(preference.input_language),
        "output_language": str(preference.output_language),
        "last_detected_input_language": preference.last_detected_input_language,
        "english_voice_configured": english_voice_configured,
        "hindi_voice_configured": hindi_voice_configured,
        "stt_available": stt_available,
        "tts_available": tts_available,
    }


def handle_voice_update_settings(
    runtime: ParikaRuntime, request: VoiceUpdateSettingsRequest
) -> dict[str, Any]:
    """
    Apply a partial update to the current Voice language preference.

    Never touches an in-flight `ChatRequest`/`VoiceRespondRequest`:
    only the shared, current preference a later `VoiceSpeakRequest`/
    `VoiceTranscribeRequest` resolves against -- see
    `VoiceLanguagePreferenceStore.resolve_input_language()`/
    `resolve_output_language()`.
    """

    from parika.modules.voice.language import (
        parse_input_language,
        parse_output_language,
    )

    preference_store = runtime.service_container.get(VoiceLanguagePreferenceStore)

    if request.input_language is not None:
        preference_store.set_input_language(
            parse_input_language(request.input_language)
        )

    if request.output_language is not None:
        preference_store.set_output_language(
            parse_output_language(request.output_language)
        )

    return handle_voice_get_settings(runtime, VoiceGetSettingsRequest())


async def handle_voice_speak_stream(
    runtime: ParikaRuntime, request: VoiceSpeakRequest, http_request=None
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Stream speech synthesis for already-known text, yielding audio
    chunks as they are synthesized.

    This is the Phase 2 incremental TTS endpoint. Unlike
    `handle_voice_speak` which returns the complete audio in one
    response, this function yields each chunk as an NDJSON line,
    allowing the client to start playback immediately while synthesis
    continues for subsequent chunks.

    The streaming uses the same `TextToSpeechToolDriver` but calls its
    `synthesize_chunks_streaming` method directly (bypassing
    `ToolManager.execute()`), since streaming requires incremental
    yield rather than a single aggregated result.
    """
    text = str(request.text).strip()

    if not text:
        yield {
            "operation_id": request.operation_id or uuid4().hex,
            "chunk_index": 0,
            "audio_base64": "",
            "mime_type": "audio/wav",
            "sample_rate": 0,
            "final": True,
            "cancelled": True,
            "output_language": None,
            "error": "Empty text",
        }
        return

    voice = request.voice or None
    requested_language = request.language or None
    operation_id = str(request.operation_id or uuid4().hex)

    # Get the TTS driver from the VoiceModuleDriver
    voice_driver = runtime.service_container.get(VoiceModuleDriver)
    tts_driver = voice_driver._tool_drivers.get(TEXT_TO_SPEECH_CAPABILITY_ID)

    if tts_driver is None:
        yield {
            "operation_id": operation_id,
            "chunk_index": 0,
            "audio_base64": "",
            "mime_type": "audio/wav",
            "sample_rate": 0,
            "final": True,
            "cancelled": True,
            "output_language": None,
            "error": "TTS driver not available",
        }
        return

    # Resolve output language
    resolved_language = tts_driver._language_preference.resolve_output_language(
        explicit=str(requested_language) if requested_language else None
    )

    # Stream chunks
    async for chunk in _stream_chunks_async(
        tts_driver,
        text=text,
        voice=str(voice) if voice else None,
        language=resolved_language,
        operation_id=operation_id,
        request=http_request,
    ):
        yield chunk


async def _stream_chunks_async(
    tts_driver,
    *,
    text: str,
    voice: str | None,
    language: str,
    operation_id: str,
    request,  # FastAPI request object for disconnect detection
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Async wrapper around the driver's synchronous streaming method.
    Yields chunks incrementally as they are synthesized.
    """
    import asyncio

    # Bounded queue for natural backpressure - maxsize=1 means
    # producer blocks after each chunk until consumer pulls it.
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    sentinel = object()
    producer_exception: Exception | None = None

    def _producer():
        nonlocal producer_exception
        try:
            for chunk in tts_driver.synthesize_chunks_streaming(
                text=text,
                voice=voice,
                language=language,
                operation_id=operation_id,
            ):
                # Check for client disconnect before putting in queue
                # This is best-effort; the actual disconnect will be detected
                # when the consumer tries to yield and the response is closed.
                try:
                    asyncio.run_coroutine_threadsafe(queue.put(chunk), loop).result()
                except RuntimeError:
                    # Event loop closed, stop producing
                    break
        except Exception as ex:
            producer_exception = ex
            try:
                asyncio.run_coroutine_threadsafe(queue.put({"_producer_error": str(ex)}), loop).result()
            except RuntimeError:
                pass
        finally:
            try:
                asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop).result()
            except RuntimeError:
                pass

    loop = asyncio.get_event_loop()

    # Start producer in executor
    producer_task = loop.run_in_executor(None, _producer)

    try:
        # Consume from queue incrementally
        while True:
            # Check if client disconnected
            if request is not None:
                try:
                    disconnected = await request.is_disconnected()
                except RuntimeError:
                    disconnected = True
                if disconnected:
                    break

            item = await queue.get()
            if item is sentinel:
                break
            if isinstance(item, dict) and "_producer_error" in item:
                yield {
                    "operation_id": operation_id,
                    "chunk_index": -1,
                    "audio_base64": "",
                    "mime_type": "audio/wav",
                    "sample_rate": 0,
                    "final": True,
                    "cancelled": False,  # Not cancelled, it's an error
                    "output_language": language,
                    "error": item["_producer_error"],
                }
                break
            yield item
    finally:
        # Wait for producer to finish (or be cancelled)
        try:
            await asyncio.wait_for(producer_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            producer_task.cancel()
