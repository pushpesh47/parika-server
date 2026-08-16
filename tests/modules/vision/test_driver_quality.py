"""
Unit tests for the deterministic-first quality/blur/rotation/anomaly
ToolDrivers (`parika.modules.vision.driver_quality`), using `FakeBrain`.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from parika.core.tool_manager.request import ToolRequest
from parika.modules.vision.driver_quality import (
    VisionAnalyzeImageQualityToolDriver,
    VisionDetectAnomaliesToolDriver,
    VisionDetectBlurToolDriver,
    VisionDetectRotationToolDriver,
)
from parika.modules.vision.exceptions import VisionImageReadError

from .conftest import analysis_result, read_result


def _b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class TestDeterministicFirstBehavior:
    """One representative test per driver -- each is the same shape."""

    def test_analyze_image_quality_never_calls_provider_by_default(
        self, fake_brain
    ) -> None:
        image = Image.new("RGB", (50, 50), color=(128, 128, 128))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))

        driver = VisionAnalyzeImageQualityToolDriver(
            brain=fake_brain,
            provider_capability_id="vision.provider_analyze_image_quality",
        )
        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert "quality_score" in response.result
        assert "explanation" not in response.result
        assert fake_brain.goals_for("vision.provider_analyze_image_quality") == []

    def test_detect_blur_never_calls_provider_by_default(self, fake_brain) -> None:
        image = Image.new("RGB", (50, 50), color=(128, 128, 128))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))

        driver = VisionDetectBlurToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_blur"
        )
        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert "variance" in response.result
        assert "is_blurry" in response.result

    def test_detect_rotation_never_calls_provider_by_default(self, fake_brain) -> None:
        image = Image.new("RGB", (50, 50), color=(128, 128, 128))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))

        driver = VisionDetectRotationToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_rotation"
        )
        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["rotation_degrees"] == 0

    def test_detect_anomalies_never_calls_provider_by_default(self, fake_brain) -> None:
        image = Image.new("RGB", (50, 50), color=(128, 128, 128))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))

        driver = VisionDetectAnomaliesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_anomalies"
        )
        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["has_anomalies"] is False


class TestOptInProviderEscalation:
    def test_instruction_triggers_provider_call(self, fake_brain) -> None:
        image = Image.new("RGB", (50, 50), color=(128, 128, 128))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))
        fake_brain.queue(
            "vision.provider_detect_blur", analysis_result("The image is not blurry.")
        )

        driver = VisionDetectBlurToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_blur"
        )

        response = driver.execute(
            ToolRequest(arguments={"path": "/a.png", "instruction": "explain"})
        )

        assert response.result["explanation"] == "The image is not blurry."


class TestRaisesWhenPathMissing:
    def test_raises(self, fake_brain) -> None:
        driver = VisionDetectBlurToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_blur"
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={}))
