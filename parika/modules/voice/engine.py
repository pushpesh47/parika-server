"""
PARIKA Voice Module - Shared Goal-Based Engine

Pure orchestration helpers reused by both `SpeechToTextToolDriver` and
`TextToSpeechToolDriver`: obtaining an input audio file's bytes through
the existing, unmodified `filesystem.read` Capability, and invoking
this Module's own Provider-backed speech Capabilities through the
existing Model Selection Framework -- exactly the same nested-`Goal`-
via-`Brain.handle()` shape `parika.modules.generation.engine` already
establishes for `image.*`/`video.*`. Introduces no new execution
architecture. No `faster-whisper`/`Piper`-specific concept exists
anywhere in this module: the nested Goal's `provider_request_builder`
returns a provider-independent `SpeechRequest`, and the result
consumed back is a provider-independent `SpeechResult` -- whichever
Provider Planner's Model Selection Framework actually resolves the
Goal to.
"""

from __future__ import annotations

from uuid import uuid4

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.goal_result import GoalResult
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.planner.goal import Goal
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.speech_request import SpeechOperation, SpeechRequest
from parika.core.provider_manager.speech_result import SpeechResult

from .exceptions import VoiceInputInvalidError, VoiceProviderError, VoiceWriteError

FILESYSTEM_READ_CAPABILITY_ID = "filesystem.read"
FILESYSTEM_WRITE_CAPABILITY_ID = "filesystem.write"


def _tool_result_payload(goal_result: GoalResult | None) -> object | None:
    if (
        goal_result is None
        or not goal_result.succeeded
        or goal_result.response is None
    ):
        return None

    backend_response = goal_result.response.outputs.get("result")
    return getattr(backend_response, "result", None)


def _failure_reason(goal_result: GoalResult | None) -> str:
    if goal_result is None:
        return "no result was produced."

    if goal_result.failure is not None:
        return str(goal_result.failure)

    if goal_result.skip_reason is not None:
        return goal_result.skip_reason

    return ""


def read_file_base64(brain: Brain, path: str) -> str:
    """
    Obtain `path`'s raw bytes, base64-encoded, exclusively through the
    existing, unmodified `filesystem.read` Capability -- the same
    Capability, Tool, security, and permission path every other
    caller (Vision, Video, OCR, Document, Generation) already uses.
    Never touches the filesystem directly.
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_READ_CAPABILITY_ID,
        inputs={"path": path, "binary": True},
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict) or "content_base64" not in payload:
        reason = _failure_reason(goal_result)
        raise VoiceInputInvalidError(
            f"Could not read audio file at '{path}'"
            + (f": {reason}" if reason else ".")
        )

    return str(payload["content_base64"])


def write_file_base64(brain: Brain, path: str, content_base64: str) -> dict:
    """
    Persist `content_base64` to `path` exclusively through the
    existing, unmodified `filesystem.write` Capability. Never touches
    the filesystem directly.
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_WRITE_CAPABILITY_ID,
        inputs={"path": path, "binary": True, "content_base64": content_base64},
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict):
        reason = _failure_reason(goal_result)
        raise VoiceWriteError(
            f"Could not write synthesized audio to '{path}'"
            + (f": {reason}" if reason else ".")
        )

    return payload


def transcribe_with_provider(
    brain: Brain,
    provider_capability_id: str,
    *,
    audio_base64: str,
    audio_mime_type: str | None,
    language: str | None,
) -> SpeechResult:
    """
    Execute one speech-to-text operation by constructing a Provider-
    backed nested Goal targeting `provider_capability_id`
    (`CapabilityCategory.SPEECH`) -- resolved, selected, and executed
    entirely by the existing, unmodified Planner/Model Selection
    Framework/Provider abstraction, exactly like
    `generation.engine.generate_with_provider()`'s role for
    Generation's Provider Capabilities.

    Raises:
        VoiceProviderError:
            If the nested Goal did not succeed (e.g. no compatible
            local speech-to-text engine is currently available).
    """

    def _build_speech_request(
        resolution: CapabilityResolution,
        model: ProviderModel,
    ) -> ProviderRequest:
        return SpeechRequest(
            operation=SpeechOperation.SPEECH_TO_TEXT,
            audio_base64=audio_base64,
            audio_mime_type=audio_mime_type,
            language=language,
        )

    goal = Goal(
        id=uuid4().hex,
        capability_id=provider_capability_id,
        inputs={"operation": "speech_to_text"},
        provider_request_builder=_build_speech_request,
        metadata={
            "execution_requirements": {"task_category": "speech_to_text"}
        },
    )

    return _handle_speech_goal(brain, goal)


def synthesize_with_provider(
    brain: Brain,
    provider_capability_id: str,
    *,
    text: str,
    voice: str | None,
    language: str | None,
) -> SpeechResult:
    """
    Execute one text-to-speech operation by constructing a Provider-
    backed nested Goal targeting `provider_capability_id`
    (`CapabilityCategory.TEXT_TO_SPEECH`) -- resolved, selected, and
    executed entirely by the existing, unmodified Planner/Model
    Selection Framework/Provider abstraction.

    Callers (see `driver_tts.py`) call this once per bounded text
    chunk, never once for an entire long response, so cancellation
    between calls remains possible.

    Raises:
        VoiceProviderError:
            If the nested Goal did not succeed (e.g. no compatible
            local text-to-speech engine is currently available).
    """

    def _build_speech_request(
        resolution: CapabilityResolution,
        model: ProviderModel,
    ) -> ProviderRequest:
        return SpeechRequest(
            operation=SpeechOperation.TEXT_TO_SPEECH,
            text=text,
            voice=voice,
            language=language,
        )

    goal = Goal(
        id=uuid4().hex,
        capability_id=provider_capability_id,
        inputs={"operation": "text_to_speech"},
        provider_request_builder=_build_speech_request,
        metadata={
            "execution_requirements": {"task_category": "text_to_speech"}
        },
    )

    return _handle_speech_goal(brain, goal)


def _handle_speech_goal(brain: Brain, goal: Goal) -> SpeechResult:
    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None

    if (
        goal_result is None
        or not goal_result.succeeded
        or goal_result.response is None
    ):
        reason = _failure_reason(goal_result)
        raise VoiceProviderError(
            "Speech operation did not succeed" + (f": {reason}" if reason else ".")
        )

    backend_response = goal_result.response.outputs.get("result")

    if isinstance(backend_response, SpeechResult):
        return backend_response

    raise VoiceProviderError(
        "Speech Provider returned an unexpected result type "
        f"({type(backend_response).__name__})."
    )
