"""
Unit tests for OcrOrientationToolDriver/OcrQualityToolDriver, using a
fake Brain (never a real Provider or a real filesystem) and real,
small synthetic images - both drivers genuinely decode/analyze pixels,
unlike the plain pass-through `OcrToolDriver`. Mirrors
`test_ocr_tool_driver.py`'s own fake-Brain shape.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.modules.ocr.analysis_driver import (
    OcrOrientationToolDriver,
    OcrQualityToolDriver,
)
from parika.modules.ocr.config import OcrToolConfig
from parika.modules.ocr.exceptions import (
    OcrDependencyUnavailableError,
    OcrImageReadError,
)


def _real_image_base64(*, width: int = 1200, height: int = 1200) -> str:
    image = Image.new("RGB", (width, height), color=(200, 200, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _FakeBrain:
    def __init__(self, responses: list[BrainResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[BrainRequest] = []

    def handle(self, request: BrainRequest) -> BrainResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _filesystem_read_result(payload: dict) -> GoalResult:
    return GoalResult(
        goal_id="g1",
        task_id="task-1",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": ToolResponse(result=payload)}),
    )


def _failed_result(reason: str) -> GoalResult:
    return GoalResult(
        goal_id="g1",
        task_id="task-1",
        status=TaskStatus.FAILED,
        response=None,
        failure=RuntimeError(reason),
    )


def _read_response(payload: dict) -> BrainResponse:
    return BrainResponse(
        request_id="r1", plan_id="p1", results=(_filesystem_read_result(payload),)
    )


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


class TestOcrOrientationToolDriver:
    def test_returns_deterministic_orientation_result(self) -> None:
        image_base64 = _real_image_base64()
        fake_brain = _FakeBrain([_read_response({"content_base64": image_base64})])

        driver = OcrOrientationToolDriver(brain=fake_brain)  # type: ignore[arg-type]
        response = driver.execute(_request(path="/mnt/dev/test/scan.png"))

        assert set(response.result) == {
            "rotation_degrees",
            "confidence",
            "exif_corrected",
        }
        assert response.result["rotation_degrees"] in (0, 90, 180, 270)
        assert response.attributes["path"] == "/mnt/dev/test/scan.png"
        # Never a second Brain call - purely deterministic, no model.
        assert len(fake_brain.requests) == 1

    def test_raises_when_path_is_missing(self) -> None:
        driver = OcrOrientationToolDriver(brain=_FakeBrain([]))  # type: ignore[arg-type]

        with pytest.raises(OcrImageReadError):
            driver.execute(_request())

    def test_raises_when_filesystem_read_fails(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1", plan_id="p1", results=(_failed_result("missing"),)
                )
            ]
        )
        driver = OcrOrientationToolDriver(brain=fake_brain)  # type: ignore[arg-type]

        with pytest.raises(OcrImageReadError):
            driver.execute(_request(path="/mnt/dev/test/missing.png"))

    def test_raises_dependency_unavailable_when_imaging_disabled(self) -> None:
        config = OcrToolConfig(preprocessing_enabled=False)
        fake_brain = _FakeBrain([])
        driver = OcrOrientationToolDriver(brain=fake_brain, config=config)  # type: ignore[arg-type]

        with pytest.raises(OcrDependencyUnavailableError):
            driver.execute(_request(path="/mnt/dev/test/scan.png"))

        # The dependency check runs before any filesystem read.
        assert len(fake_brain.requests) == 0


class TestOcrQualityToolDriver:
    def test_returns_quality_assessment(self) -> None:
        image_base64 = _real_image_base64()
        fake_brain = _FakeBrain([_read_response({"content_base64": image_base64})])

        driver = OcrQualityToolDriver(brain=fake_brain)  # type: ignore[arg-type]
        response = driver.execute(_request(path="/mnt/dev/test/scan.png"))

        assert 0.0 <= response.result["quality_score"] <= 1.0
        assert response.result["width"] == 1200
        assert response.result["height"] == 1200
        assert isinstance(response.result["warnings"], list)
        assert len(fake_brain.requests) == 1

    def test_low_resolution_image_triggers_warning(self) -> None:
        image_base64 = _real_image_base64(width=50, height=50)
        fake_brain = _FakeBrain([_read_response({"content_base64": image_base64})])

        driver = OcrQualityToolDriver(brain=fake_brain)  # type: ignore[arg-type]
        response = driver.execute(_request(path="/mnt/dev/test/tiny.png"))

        assert response.result["is_low_resolution"]
        assert any("resolution" in warning for warning in response.result["warnings"])
        assert response.result["meets_minimum_quality"] in (True, False)

    def test_raises_when_path_is_missing(self) -> None:
        driver = OcrQualityToolDriver(brain=_FakeBrain([]))  # type: ignore[arg-type]

        with pytest.raises(OcrImageReadError):
            driver.execute(_request())

    def test_raises_dependency_unavailable_when_imaging_disabled(self) -> None:
        config = OcrToolConfig(preprocessing_enabled=False)
        driver = OcrQualityToolDriver(brain=_FakeBrain([]), config=config)  # type: ignore[arg-type]

        with pytest.raises(OcrDependencyUnavailableError):
            driver.execute(_request(path="/mnt/dev/test/scan.png"))
