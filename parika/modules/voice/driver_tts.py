"""
PARIKA Voice Module - Text-to-Speech ToolDriver

Implements `voice.text_to_speech`: an orchestrator ToolDriver that
splits its input text into small, bounded chunks
(`text_chunking.split_into_speech_chunks()`) and synthesizes each one,
in order, through this Module's own Provider-backed Capability
(`voice.provider_text_to_speech`, resolved by Planner's Model
Selection Framework to whichever compatible Provider is registered --
the Local Speech Provider today), checking `TtsOperationRegistry
.is_cancelled()` between chunks so a concurrent
`POST /voice/speak/{operation_id}/stop` request can take effect
mid-synthesis rather than only after the entire response has already
been synthesized.

Relationship to `ToolManager`'s progress lifecycle guard (Section 19
of the Voice architecture task): cancellation is reported through
`self._progress.completed(..., cancelled=True)`, never through
`failed()` and never by raising -- stopping a `speak` operation is a
normal, successful outcome (a partial result), not an execution
failure, exactly like `PARIKA_Core_Coding_Standards.md`'s progress
contract already allows for any Tool that can legitimately produce a
partial success. This driver uses the reference-safe
`started()`/`try`/`completed()`/`except: failed(); raise` shape (see
`parika.modules.coding_agent.driver.CodingAgentToolDriver` for the
established precedent) specifically so a genuine synthesis failure
(as opposed to a user-requested stop) still reports `failed()` before
propagating -- the shared `ToolManager` guard closes any remaining
gap either way; this driver never needs its own duplicate-termination
guard.
"""

from __future__ import annotations

from uuid import uuid4

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine
from .audio import concatenate_wav_chunks
from .config import VoiceToolConfig
from .exceptions import VoiceInputInvalidError, VoiceWriteError
from .language import VoiceLanguagePreferenceStore
from .operation_registry import TtsOperationRegistry
from .text_chunking import split_into_speech_chunks


class TextToSpeechToolDriver:
    """`ToolDriver` implementing `voice.text_to_speech`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        config: VoiceToolConfig,
        operation_registry: TtsOperationRegistry,
        language_preference: VoiceLanguagePreferenceStore | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._config = config
        self._operations = operation_registry
        self._language_preference = (
            language_preference or VoiceLanguagePreferenceStore()
        )
        self._progress = progress_reporter or NullProgressReporter(
            "voice.text_to_speech"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        text = str(request.arguments.get("text", "")).strip()

        if not text:
            raise VoiceInputInvalidError(
                "request.arguments['text'] must be a non-empty string."
            )

        voice = request.arguments.get("voice") or None
        requested_language = request.arguments.get("language") or None
        output_path = request.arguments.get("output_path")
        operation_id = str(
            request.arguments.get("operation_id") or uuid4().hex
        )

        # Resolve the *output* language once, up front, per this
        # Module's documented TTS language-selection order: explicit
        # request argument -> current output-language preference
        # (`en`/`hi` directly, or `follow_input` against the most
        # recently detected/used input language) -> configured
        # fallback. Never lets the chat model choose a voice/language
        # itself -- see `language.VoiceLanguagePreferenceStore
        # .resolve_output_language()`.
        resolved_language = self._language_preference.resolve_output_language(
            explicit=str(requested_language) if requested_language else None
        )

        self._progress.started(message="Synthesizing speech...")
        self._operations.begin(operation_id)

        try:
            wav_bytes, sample_rate, cancelled = self._synthesize_chunks(
                text,
                voice=str(voice) if voice else None,
                language=resolved_language,
                operation_id=operation_id,
            )

        except Exception:
            self._operations.fail(operation_id)
            self._progress.failed()
            raise

        result: dict[str, object] = {
            "operation_id": operation_id,
            "audio_base64": _base64(wav_bytes),
            "mime_type": "audio/wav",
            "sample_rate": sample_rate,
            "cancelled": cancelled,
            "language": resolved_language,
        }

        if output_path and wav_bytes:
            self._progress.progress(message="Writing audio...")
            written = engine.write_file_base64(
                self._brain, str(output_path), result["audio_base64"]
            )

            if not isinstance(written, dict):
                raise VoiceWriteError(
                    f"Could not write synthesized audio to '{output_path}'."
                )

            result["output_path"] = str(output_path)

        if cancelled:
            self._operations.cancel(operation_id)  # idempotent; keeps status CANCELLED
            self._progress.completed(message="Stopped by user.", cancelled=True)
        else:
            self._operations.complete(operation_id)
            self._progress.completed(message="Completed.")

        return ToolResponse(result=result, attributes={"operation_id": operation_id})

    def _synthesize_chunks(
        self,
        text: str,
        *,
        voice: str | None,
        language: str | None,
        operation_id: str,
    ) -> tuple[bytes, int, bool]:
        chunks = split_into_speech_chunks(
            text, max_characters=self._config.tts_chunk_max_characters
        )
        wav_chunks: list[bytes] = []

        for chunk in chunks:
            if self._operations.is_cancelled(operation_id):
                break

            result = engine.synthesize_with_provider(
                self._brain,
                self._provider_capability_id,
                text=chunk,
                voice=voice,
                language=language,
            )
            wav_chunks.append(_decode(result.audio_base64))

        cancelled = self._operations.is_cancelled(operation_id) or len(
            wav_chunks
        ) < len(chunks)

        if not wav_chunks:
            return b"", 0, cancelled

        wav_bytes, sample_rate = concatenate_wav_chunks(tuple(wav_chunks))

        return wav_bytes, sample_rate, cancelled


def _decode(audio_base64: str) -> bytes:
    import base64

    return base64.b64decode(audio_base64)


def _base64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")
