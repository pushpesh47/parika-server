"""
Shared fake-Brain test support for the Voice Module's ToolDrivers,
mirroring `tests/modules/generation/conftest.py`'s own shape exactly.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.speech_result import SpeechResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.response import ToolResponse
from parika.modules.voice.audio import pcm16_to_wav

AUDIO_BASE64 = base64.b64encode(b"fake-audio-bytes-one").decode("ascii")
SILENT_PCM = b"\x00\x00" * 400


class FakeBrain:
    """Dispatches queued `BrainResponse`s by the first Goal's `capability_id`."""

    def __init__(self) -> None:
        self.requests: list[BrainRequest] = []
        self._queues: dict[str, list[BrainResponse]] = {}

    def queue(self, capability_id: str, response: BrainResponse) -> None:
        self._queues.setdefault(capability_id, []).append(response)

    def handle(self, request: BrainRequest) -> BrainResponse:
        self.requests.append(request)
        capability_id = request.goals[0].capability_id
        queue = self._queues.get(capability_id)

        if not queue:
            raise AssertionError(
                f"FakeBrain: no queued response for capability "
                f"'{capability_id}'."
            )

        return queue.pop(0)

    def goals_for(self, capability_id: str) -> list[Any]:
        return [
            goal
            for request in self.requests
            for goal in request.goals
            if goal.capability_id == capability_id
        ]


def read_result(payload: dict | None = None) -> BrainResponse:
    body = {"content_base64": AUDIO_BASE64, "size": 123}
    if payload:
        body.update(payload)

    return BrainResponse(
        request_id="r-read",
        plan_id="p-read",
        results=(
            GoalResult(
                goal_id="g-read",
                capability_id="filesystem.read",
                task_id="t-read",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(outputs={"result": ToolResponse(result=body)}),
            ),
        ),
    )


def write_result(path: str = "/tmp/out.wav") -> BrainResponse:
    return BrainResponse(
        request_id="r-write",
        plan_id="p-write",
        results=(
            GoalResult(
                goal_id="g-write",
                capability_id="filesystem.write",
                task_id="t-write",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": ToolResponse(
                            result={"path": path, "bytes_written": 10, "mode": "overwrite"}
                        )
                    }
                ),
            ),
        ),
    )


def stt_result(*, text: str = "hello world", language: str | None = "en") -> BrainResponse:
    return BrainResponse(
        request_id="r-stt",
        plan_id="p-stt",
        results=(
            GoalResult(
                goal_id="g-stt",
                capability_id="voice.provider_speech_to_text",
                task_id="t-stt",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": SpeechResult(
                            text=text,
                            language_detected=language,
                            duration_seconds=1.5,
                        )
                    }
                ),
            ),
        ),
    )


def tts_result(
    *, pcm_bytes: bytes = SILENT_PCM, sample_rate: int = 16000
) -> BrainResponse:
    wav_bytes = pcm16_to_wav(pcm_bytes, sample_rate=sample_rate)

    return BrainResponse(
        request_id="r-tts",
        plan_id="p-tts",
        results=(
            GoalResult(
                goal_id="g-tts",
                capability_id="voice.provider_text_to_speech",
                task_id="t-tts",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": SpeechResult(
                            audio_base64=base64.b64encode(wav_bytes).decode("ascii"),
                            audio_mime_type="audio/wav",
                            sample_rate=sample_rate,
                        )
                    }
                ),
            ),
        ),
    )


def failed_result(reason: str) -> BrainResponse:
    return BrainResponse(
        request_id="r-failed",
        plan_id="p-failed",
        results=(
            GoalResult(
                goal_id="g-failed",
                capability_id="test.failed",
                task_id="t-failed",
                status=TaskStatus.FAILED,
                response=None,
                failure=RuntimeError(reason),
            ),
        ),
    )


@pytest.fixture
def fake_brain() -> FakeBrain:
    return FakeBrain()
