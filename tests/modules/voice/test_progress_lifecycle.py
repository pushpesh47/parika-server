"""
Regression tests proving the Voice Module's ToolDrivers
(`SpeechToTextToolDriver`/`TextToSpeechToolDriver`) correctly
integrate with the existing, unmodified `ToolManager` progress
lifecycle guard (see
`tests/core/tool_manager/test_tool_manager_progress_guard.py`) without
reintroducing the previously-fixed CLI/progress lifecycle problem, and
that a caller-requested "Stop Speaking" is reported as exactly one
normal `completed()` event -- never a `failed()`, never a duplicate,
and never left open -- mirroring
`tests/modules/generation/test_progress_lifecycle.py`'s own shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.tool_manager.exceptions import ToolExecutionError
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter, ProgressStage
from parika.modules.voice.config import VoiceToolConfig
from parika.modules.voice.driver_stt import SpeechToTextToolDriver
from parika.modules.voice.driver_tts import TextToSpeechToolDriver
from parika.modules.voice.operation_registry import TtsOperationRegistry

from .conftest import AUDIO_BASE64, failed_result, stt_result, tts_result


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


class _SpinnerCounter:
    """
    Mirrors `SpinnerProgressRenderer._active` (spinner_view.py): the
    CLI-visible invariant every scenario below asserts is that this
    count returns to exactly 0 once the call has fully unwound,
    regardless of success, failure, or cancellation.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self.active = 0
        self.terminal_stages: list[ProgressStage] = []

        event_bus.subscribe("progress.started", self._on_started)
        event_bus.subscribe("progress.completed", self._on_terminal)
        event_bus.subscribe("progress.failed", self._on_terminal)

    def _on_started(self, event: Any) -> None:
        self.active += 1

    def _on_terminal(self, event: Any) -> None:
        self.active -= 1
        self.terminal_stages.append(event.stage)


def test_stt_success_reports_exactly_one_completed_event(
    fake_brain, tool_manager: ToolManager, event_bus: EventBus
) -> None:
    fake_brain.queue("voice.provider_speech_to_text", stt_result())

    progress = ProgressReporter(event_bus, "voice.speech_to_text")
    driver = SpeechToTextToolDriver(
        brain=fake_brain,
        provider_capability_id="voice.provider_speech_to_text",
        progress_reporter=progress,
    )
    tool_manager.register(
        Tool(id="tool.voice_speech_to_text", name="Speech to Text", version="1.0.0",
             description="Transcribes audio."),
        driver,
    )

    counter = _SpinnerCounter(event_bus)

    tool_manager.execute(
        "tool.voice_speech_to_text",
        ToolRequest(arguments={"audio_base64": AUDIO_BASE64}),
    )

    assert counter.active == 0
    assert counter.terminal_stages == [ProgressStage.COMPLETED]


def test_stt_provider_failure_does_not_leave_progress_active(
    fake_brain, tool_manager: ToolManager, event_bus: EventBus
) -> None:
    # `SpeechToTextToolDriver` uses the "naive future-style" shape
    # (started() with no enclosing try/except) exactly like
    # `ImageGenerateToolDriver` -- the shared ToolManager guard, not
    # this driver, is responsible for synthesizing the missing
    # terminal event when the nested provider Goal fails.
    fake_brain.queue(
        "voice.provider_speech_to_text",
        failed_result("no compatible speech-to-text model is installed"),
    )

    progress = ProgressReporter(event_bus, "voice.speech_to_text")
    driver = SpeechToTextToolDriver(
        brain=fake_brain,
        provider_capability_id="voice.provider_speech_to_text",
        progress_reporter=progress,
    )
    tool_manager.register(
        Tool(id="tool.voice_speech_to_text", name="Speech to Text", version="1.0.0",
             description="Transcribes audio."),
        driver,
    )

    counter = _SpinnerCounter(event_bus)

    with pytest.raises(ToolExecutionError):
        tool_manager.execute(
            "tool.voice_speech_to_text",
            ToolRequest(arguments={"audio_base64": AUDIO_BASE64}),
        )

    assert counter.active == 0
    assert counter.terminal_stages == [ProgressStage.FAILED]


def test_tts_success_reports_exactly_one_completed_event(
    fake_brain, tool_manager: ToolManager, event_bus: EventBus
) -> None:
    fake_brain.queue("voice.provider_text_to_speech", tts_result())

    progress = ProgressReporter(event_bus, "voice.text_to_speech")
    driver = TextToSpeechToolDriver(
        brain=fake_brain,
        provider_capability_id="voice.provider_text_to_speech",
        config=VoiceToolConfig(),
        operation_registry=TtsOperationRegistry(),
        progress_reporter=progress,
    )
    tool_manager.register(
        Tool(id="tool.voice_text_to_speech", name="Text to Speech", version="1.0.0",
             description="Synthesizes speech."),
        driver,
    )

    counter = _SpinnerCounter(event_bus)

    tool_manager.execute(
        "tool.voice_text_to_speech",
        ToolRequest(arguments={"text": "Hello there."}),
    )

    assert counter.active == 0
    assert counter.terminal_stages == [ProgressStage.COMPLETED]


def test_tts_provider_failure_does_not_leave_progress_active(
    fake_brain, tool_manager: ToolManager, event_bus: EventBus
) -> None:
    # `TextToSpeechToolDriver` uses the reference-safe
    # started()/try/except: failed(); raise shape, so it reports its
    # own failed() -- the shared guard sees the node already
    # terminated and adds nothing further (no duplicate event).
    fake_brain.queue(
        "voice.provider_text_to_speech",
        failed_result("no compatible text-to-speech model is installed"),
    )

    progress = ProgressReporter(event_bus, "voice.text_to_speech")
    driver = TextToSpeechToolDriver(
        brain=fake_brain,
        provider_capability_id="voice.provider_text_to_speech",
        config=VoiceToolConfig(),
        operation_registry=TtsOperationRegistry(),
        progress_reporter=progress,
    )
    tool_manager.register(
        Tool(id="tool.voice_text_to_speech", name="Text to Speech", version="1.0.0",
             description="Synthesizes speech."),
        driver,
    )

    counter = _SpinnerCounter(event_bus)

    with pytest.raises(ToolExecutionError):
        tool_manager.execute(
            "tool.voice_text_to_speech",
            ToolRequest(arguments={"text": "Hello there.", "operation_id": "op-1"}),
        )

    assert counter.active == 0
    assert counter.terminal_stages == [ProgressStage.FAILED]


def test_tts_cancellation_reports_exactly_one_completed_event_never_failed(
    fake_brain, tool_manager: ToolManager, event_bus: EventBus
) -> None:
    """
    Stopping a `speak` operation is a normal, successful (partial)
    outcome, never an execution failure (Section 10): the Tool
    execution itself still reports exactly one `completed()` event,
    never `failed()`, and the CLI-visible active count still returns
    to 0.
    """

    registry = TtsOperationRegistry()
    registry.cancel("op-1")  # preemptive cancel -- see operation_registry tests

    progress = ProgressReporter(event_bus, "voice.text_to_speech")
    driver = TextToSpeechToolDriver(
        brain=fake_brain,
        provider_capability_id="voice.provider_text_to_speech",
        config=VoiceToolConfig(),
        operation_registry=registry,
        progress_reporter=progress,
    )
    tool_manager.register(
        Tool(id="tool.voice_text_to_speech", name="Text to Speech", version="1.0.0",
             description="Synthesizes speech."),
        driver,
    )

    counter = _SpinnerCounter(event_bus)

    response = tool_manager.execute(
        "tool.voice_text_to_speech",
        ToolRequest(arguments={"text": "Hello there.", "operation_id": "op-1"}),
    )

    assert response.result["cancelled"] is True
    assert counter.active == 0
    assert counter.terminal_stages == [ProgressStage.COMPLETED]
    # No provider goal was ever dispatched -- the cancellation was
    # observed before the first chunk.
    assert fake_brain.goals_for("voice.provider_text_to_speech") == []


def test_nested_stt_then_tts_execution_isolates_progress_terminals(
    fake_brain, tool_manager: ToolManager, event_bus: EventBus
) -> None:
    """
    A caller that runs `speech_to_text` and then `text_to_speech` in
    the same turn (e.g. `voice.respond` followed later by
    `voice.speak`) must never have one execution's terminal event
    attributed to the other's still-tracked progress node -- proven
    here by running both sequentially against one shared
    `ToolManager`/`EventBus` and asserting each reports exactly one
    terminal event of its own.
    """

    fake_brain.queue("voice.provider_speech_to_text", stt_result())
    fake_brain.queue("voice.provider_text_to_speech", tts_result())

    stt_progress = ProgressReporter(event_bus, "voice.speech_to_text")
    tts_progress = ProgressReporter(event_bus, "voice.text_to_speech")

    tool_manager.register(
        Tool(id="tool.voice_speech_to_text", name="Speech to Text", version="1.0.0",
             description="Transcribes audio."),
        SpeechToTextToolDriver(
            brain=fake_brain,
            provider_capability_id="voice.provider_speech_to_text",
            progress_reporter=stt_progress,
        ),
    )
    tool_manager.register(
        Tool(id="tool.voice_text_to_speech", name="Text to Speech", version="1.0.0",
             description="Synthesizes speech."),
        TextToSpeechToolDriver(
            brain=fake_brain,
            provider_capability_id="voice.provider_text_to_speech",
            config=VoiceToolConfig(),
            operation_registry=TtsOperationRegistry(),
            progress_reporter=tts_progress,
        ),
    )

    counter = _SpinnerCounter(event_bus)

    tool_manager.execute(
        "tool.voice_speech_to_text",
        ToolRequest(arguments={"audio_base64": AUDIO_BASE64}),
    )
    tool_manager.execute(
        "tool.voice_text_to_speech",
        ToolRequest(arguments={"text": "Hello there."}),
    )

    assert counter.active == 0
    assert counter.terminal_stages == [
        ProgressStage.COMPLETED,
        ProgressStage.COMPLETED,
    ]
