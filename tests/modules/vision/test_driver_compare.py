"""
Unit tests for `VisionCompareImagesToolDriver`/`VisionDetectDifferencesToolDriver`
(`parika.modules.vision.driver_compare`), using `FakeBrain` -- never a
real Provider or filesystem.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from parika.core.tool_manager.request import ToolRequest
from parika.modules.vision.driver_compare import (
    VisionCompareImagesToolDriver,
    VisionDetectDifferencesToolDriver,
)
from parika.modules.vision.exceptions import VisionImageReadError

from .conftest import IMAGE_B_BASE64, IMAGE_BASE64, analysis_result, read_result

_PROVIDER_CAPABILITY_ID = "vision.provider_compare_images"


def _image_base64(image: Image.Image) -> str:
    import base64
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class TestVisionCompareImagesToolDriver:
    def test_returns_deterministic_metrics_without_calling_provider(
        self, fake_brain
    ) -> None:
        image = Image.new("RGB", (100, 100), color=(255, 255, 255))
        image_bytes = _image_base64(image)

        fake_brain.queue("filesystem.read", read_result({"content_base64": image_bytes}))
        fake_brain.queue("filesystem.read", read_result({"content_base64": image_bytes}))

        driver = VisionCompareImagesToolDriver(
            brain=fake_brain, provider_capability_id=_PROVIDER_CAPABILITY_ID
        )

        response = driver.execute(
            ToolRequest(arguments={"path_a": "/a.png", "path_b": "/b.png"})
        )

        assert response.result["overall_similarity"] == 1.0
        assert "explanation" not in response.result
        assert fake_brain.goals_for(_PROVIDER_CAPABILITY_ID) == []

    def test_calls_provider_only_when_instruction_given(self, fake_brain) -> None:
        image = Image.new("RGB", (100, 100), color=(255, 255, 255))
        image_bytes = _image_base64(image)

        fake_brain.queue("filesystem.read", read_result({"content_base64": image_bytes}))
        fake_brain.queue("filesystem.read", read_result({"content_base64": image_bytes}))
        fake_brain.queue(_PROVIDER_CAPABILITY_ID, analysis_result("They look identical."))

        driver = VisionCompareImagesToolDriver(
            brain=fake_brain, provider_capability_id=_PROVIDER_CAPABILITY_ID
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "path_a": "/a.png",
                    "path_b": "/b.png",
                    "instruction": "Explain the comparison.",
                }
            )
        )

        assert response.result["explanation"] == "They look identical."
        provider_goal = fake_brain.goals_for(_PROVIDER_CAPABILITY_ID)[0]
        built_request = provider_goal.provider_request_builder(None, None)
        assert built_request.messages[0].images == (image_bytes, image_bytes)

    def test_raises_when_a_path_is_missing(self, fake_brain) -> None:
        driver = VisionCompareImagesToolDriver(
            brain=fake_brain, provider_capability_id=_PROVIDER_CAPABILITY_ID
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={"path_a": "/a.png"}))


class TestVisionDetectDifferencesToolDriver:
    def test_locates_regions_without_calling_provider(self, fake_brain) -> None:
        image_a = Image.new("RGB", (200, 200), color=(255, 255, 255))
        image_b = image_a.copy()
        ImageDraw.Draw(image_b).rectangle([50, 50, 120, 120], fill=(0, 0, 0))

        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _image_base64(image_a)})
        )
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _image_base64(image_b)})
        )

        driver = VisionDetectDifferencesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_differences"
        )

        response = driver.execute(
            ToolRequest(arguments={"path_a": "/a.png", "path_b": "/b.png"})
        )

        assert response.result["region_count"] >= 1
        assert response.result["difference_ratio"] > 0
        assert "explanation" not in response.result

    def test_raises_when_paths_missing(self, fake_brain) -> None:
        driver = VisionDetectDifferencesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_differences"
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={}))
