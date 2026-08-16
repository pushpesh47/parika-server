"""
Regression test for the confirmed ProgressReporter lifecycle leak the
audit report identified in this Module's ToolDrivers
(`driver_image.py`/`driver_video.py`): `self._progress.started()`
with no enclosing try/except, so a provider/ComfyUI failure left that
progress node open forever.

The fix lives at the shared `ToolManager.execute()` boundary (see
`tests/core/tool_manager/test_tool_manager_progress_guard.py`), not in
this Module's drivers themselves. This test proves that boundary
actually protects the real, previously-leaking driver end-to-end: a
`VideoGenerateToolDriver` registered with a real `ToolManager`, driven
through a forced ComfyUI/provider failure, must leave no progress node
active once the call returns.
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
from parika.core.utilities.progress import ProgressReporter
from parika.modules.generation.config import GenerationToolConfig
from parika.modules.generation.driver_video import VideoGenerateToolDriver

from .conftest import failed_result


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


def test_comfyui_provider_failure_does_not_leave_progress_active(
    fake_brain,
    tool_manager: ToolManager,
    event_bus: EventBus,
) -> None:
    # Reproduces the reported CLI symptom's root failure: the nested
    # `video.provider_generate` Goal fails (e.g. ComfyUI timeout/
    # workflow error), so `engine.generate_with_provider()` raises
    # `GenerationProviderError` from inside
    # `VideoGenerateToolDriver.execute()`, *after* that driver's own
    # `self._progress.started()` already fired.
    fake_brain.queue(
        "video.provider_generate",
        failed_result("ComfyUI workflow execution timed out."),
    )

    progress = ProgressReporter(event_bus, "video.generate")
    driver = VideoGenerateToolDriver(
        brain=fake_brain,
        provider_capability_id="video.provider_generate",
        config=GenerationToolConfig(output_directory="generated"),
        progress_reporter=progress,
    )
    tool_manager.register(
        Tool(
            id="video.generate",
            name="Video Generate",
            version="1.0.0",
            description="Generates a video from a text prompt.",
        ),
        driver,
    )

    # Mirrors `SpinnerProgressRenderer._active` (spinner_view.py):
    # the CLI-visible invariant this fix restores is that this count
    # returns to 0 once the failed call has fully unwound.
    active = 0

    def _on_started(event: Any) -> None:
        nonlocal active
        active += 1

    def _on_terminal(event: Any) -> None:
        nonlocal active
        active -= 1

    event_bus.subscribe("progress.started", _on_started)
    event_bus.subscribe("progress.completed", _on_terminal)
    event_bus.subscribe("progress.failed", _on_terminal)

    with pytest.raises(ToolExecutionError):
        tool_manager.execute(
            "video.generate",
            ToolRequest(
                arguments={
                    "prompt": "a spaceship flying through a nebula",
                    "duration_seconds": 10,
                }
            ),
        )

    assert active == 0
