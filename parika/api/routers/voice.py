"""
PARIKA API - Voice Router

Server-side Voice capability (Section 3 of the Voice architecture
task): a Web UI, Console-in-the-future, mobile, or desktop client
sends audio here and receives text (and, independently, optionally
requests speech); no client ever needs its own STT/TTS implementation.

`POST /transcribe` and `POST /speak` are independent, single-direction
operations. `POST /respond` is the audio-input analogue of
`POST /api/v1/chat`: it enters the *same* text pipeline
(`parika/api/handlers/chat.py::handle_chat()`), never a second
reasoning pipeline, and never auto-triggers speech output -- see
`parika/api/handlers/voice.py`'s module docstring for exactly why.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.backend import AuthContext
from ..auth.dependency import RequireAuth
from ..dependencies import get_core_execution_owner, get_runtime
from ..handlers.voice import handle_voice_get_settings
from ..requests import (
    VoiceRespondRequest as InternalVoiceRespondRequest,
    VoiceSpeakRequest as InternalVoiceSpeakRequest,
    VoiceStopSpeakingRequest as InternalVoiceStopSpeakingRequest,
    VoiceTranscribeRequest as InternalVoiceTranscribeRequest,
    VoiceUpdateSettingsRequest as InternalVoiceUpdateSettingsRequest,
)
from ..schemas.voice import (
    VoiceRespondRequestBody,
    VoiceRespondResponseBody,
    VoiceSettingsResponseBody,
    VoiceSettingsUpdateRequestBody,
    VoiceSpeakRequestBody,
    VoiceSpeakResponseBody,
    VoiceStopSpeakingResponseBody,
    VoiceTranscribeRequestBody,
    VoiceTranscribeResponseBody,
)

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe", response_model=VoiceTranscribeResponseBody)
async def transcribe(
    body: VoiceTranscribeRequestBody,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> VoiceTranscribeResponseBody:
    """
    `audio -> text`. Never enters the text pipeline; use `/respond`
    for that.
    """

    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(
            InternalVoiceTranscribeRequest(
                audio_base64=body.audio_base64,
                mime_type=body.mime_type,
                language=body.language,
            )
        )
    )
    
    # Await the result without blocking the ASGI event loop
    result = await future

    return VoiceTranscribeResponseBody.model_validate(result)


@router.post("/respond", response_model=VoiceRespondResponseBody)
async def respond(
    body: VoiceRespondRequestBody,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> VoiceRespondResponseBody:
    """
    `audio -> speech_to_text -> the same non-streaming chat pipeline
    POST /api/v1/chat uses -> canonical text response`.

    Never synthesizes speech for the reply. A client that also wants
    a spoken response calls `POST /speak` with the returned `message`
    once it has decided (independently, and possibly only once the
    reply has actually arrived) that speech output is still wanted --
    see `docs/architecture/adr/0002-voice-capability.md`'s "dynamic
    TTS control" decision for why this is the correct, and only, way
    every input/output combination and every dynamic-preference-change
    scenario (including a language-preference change, see `GET`/
    `PUT /settings` below) stays correct.
    """

    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(
            InternalVoiceRespondRequest(
                audio_base64=body.audio_base64,
                mime_type=body.mime_type,
                language=body.language,
                session_id=body.session_id,
            )
        )
    )
    
    # Await the result without blocking the ASGI event loop
    result = await future

    return VoiceRespondResponseBody.model_validate(result)


@router.post("/speak", response_model=VoiceSpeakResponseBody)
async def speak(
    body: VoiceSpeakRequestBody,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> VoiceSpeakResponseBody:
    """
    `text -> audio`. Fully independent of chat/respond -- never
    generates the text itself.

    Supply `operation_id` (a caller-generated identifier) to be able
    to cancel this operation mid-synthesis via
    `POST /speak/{operation_id}/stop` from a concurrent request.
    """

    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(
            InternalVoiceSpeakRequest(
                text=body.text,
                voice=body.voice,
                language=body.language,
                operation_id=body.operation_id,
            )
        )
    )
    
    # Await the result without blocking the ASGI event loop
    result = await future

    return VoiceSpeakResponseBody.model_validate(result)


@router.post("/speak/{operation_id}/stop", response_model=VoiceStopSpeakingResponseBody)
async def stop_speaking(
    operation_id: str,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> VoiceStopSpeakingResponseBody:
    """
    Cancel an in-progress `/speak` operation.

    Never cancels, fails, or otherwise affects any PARIKA request or
    its already-produced text response -- only the independent speech-
    synthesis operation identified by `operation_id`.
    """

    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(
            InternalVoiceStopSpeakingRequest(operation_id=operation_id)
        )
    )
    
    # Await the result without blocking the ASGI event loop
    result = await future

    return VoiceStopSpeakingResponseBody.model_validate(result)


@router.get("/settings", response_model=VoiceSettingsResponseBody)
async def get_settings(
    auth: AuthContext = RequireAuth,
    runtime=Depends(get_runtime),
) -> VoiceSettingsResponseBody:
    """
    Read the current Voice language preference (input/output) plus a
    small, non-sensitive availability summary -- the authoritative
    server-side state a client renders; the client never determines
    input/output language itself (Section 26's "Client Contract").
    """
    from ..requests import VoiceGetSettingsRequest
    result = handle_voice_get_settings(runtime, VoiceGetSettingsRequest())
    return VoiceSettingsResponseBody.model_validate(result)


@router.put("/settings", response_model=VoiceSettingsResponseBody)
async def update_settings(
    body: VoiceSettingsUpdateRequestBody,
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> VoiceSettingsResponseBody:
    """
    Update the current Voice language preference. An omitted field
    leaves that preference unchanged.

    Never cancels, modifies, or otherwise affects any in-flight
    `POST /respond`/`POST /api/v1/chat` request or its already-
    produced canonical text response -- only the shared, current
    preference a later `/transcribe`/`/speak` call resolves against.
    """

    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: core_execution_owner.router.dispatch(
            InternalVoiceUpdateSettingsRequest(
                input_language=body.input_language,
                output_language=body.output_language,
            )
        )
    )
    
    # Await the result without blocking the ASGI event loop
    result = await future

    return VoiceSettingsResponseBody.model_validate(result)
