"""
Unit tests for `VisionCountObjectsToolDriver`/`VisionClassifyImageToolDriver`
(`parika.modules.vision.driver_counting`), using `FakeBrain`.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageDraw

from parika.core.tool_manager.request import ToolRequest
from parika.modules.vision.driver_counting import (
    VisionClassifyImageToolDriver,
    VisionCountObjectsToolDriver,
)
from parika.modules.vision.exceptions import VisionImageReadError

from .conftest import analysis_result, read_result

_COUNT_PROVIDER_ID = "vision.provider_count_objects"
_CLASSIFY_PROVIDER_ID = "vision.provider_classify_image"


def _b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _simple_blob_image() -> Image.Image:
    image = Image.new("L", (300, 300), color=255)
    draw = ImageDraw.Draw(image)
    for cx in (40, 100, 160, 220, 280):
        draw.ellipse([cx - 15, 140, cx + 15, 170], fill=0)
    return image.convert("RGB")


class TestVisionCountObjectsToolDriver:
    def test_uses_deterministic_count_for_simple_scene_without_instruction(
        self, fake_brain
    ) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_simple_blob_image())})
        )

        driver = VisionCountObjectsToolDriver(
            brain=fake_brain, provider_capability_id=_COUNT_PROVIDER_ID
        )

        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["method"] == "deterministic_blob_count"
        assert response.result["count"] == 5
        assert fake_brain.goals_for(_COUNT_PROVIDER_ID) == []

    def test_falls_back_to_model_when_instruction_names_a_specific_object(
        self, fake_brain
    ) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_simple_blob_image())})
        )
        fake_brain.queue(_COUNT_PROVIDER_ID, analysis_result("3 cars."))

        driver = VisionCountObjectsToolDriver(
            brain=fake_brain, provider_capability_id=_COUNT_PROVIDER_ID
        )

        response = driver.execute(
            ToolRequest(arguments={"path": "/a.png", "instruction": "count the cars"})
        )

        assert response.result["method"] == "vision_model"
        assert response.result["text"] == "3 cars."

    def test_falls_back_to_model_when_deterministic_count_is_not_confident(
        self, fake_brain
    ) -> None:
        noisy = Image.new("RGB", (100, 100), color=(128, 128, 128))
        pixels = noisy.load()
        for y in range(100):
            for x in range(100):
                if (x + y) % 2 == 0:
                    pixels[x, y] = (0, 0, 0)

        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(noisy)}))
        fake_brain.queue(_COUNT_PROVIDER_ID, analysis_result("Many small regions."))

        driver = VisionCountObjectsToolDriver(
            brain=fake_brain, provider_capability_id=_COUNT_PROVIDER_ID
        )

        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["method"] == "vision_model"

    def test_raises_when_path_missing(self, fake_brain) -> None:
        driver = VisionCountObjectsToolDriver(
            brain=fake_brain, provider_capability_id=_COUNT_PROVIDER_ID
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={}))


class TestVisionClassifyImageToolDriver:
    def test_uses_heuristic_when_no_labels_given(self, fake_brain) -> None:
        ui = Image.new("RGB", (300, 300), color=(245, 245, 245))
        ImageDraw.Draw(ui).rectangle([10, 10, 290, 40], fill=(220, 220, 220))

        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(ui)}))

        driver = VisionClassifyImageToolDriver(
            brain=fake_brain, provider_capability_id=_CLASSIFY_PROVIDER_ID
        )

        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["method"] == "deterministic_heuristic"
        assert "label" in response.result
        assert fake_brain.goals_for(_CLASSIFY_PROVIDER_ID) == []

    def test_uses_model_when_labels_given(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read",
            read_result({"content_base64": _b64(Image.new("RGB", (50, 50)))}),
        )
        fake_brain.queue(_CLASSIFY_PROVIDER_ID, analysis_result("cat"))

        driver = VisionClassifyImageToolDriver(
            brain=fake_brain, provider_capability_id=_CLASSIFY_PROVIDER_ID
        )

        response = driver.execute(
            ToolRequest(arguments={"path": "/a.png", "labels": ["cat", "dog"]})
        )

        assert response.result["method"] == "vision_model"
        assert response.result["text"] == "cat"
        assert response.result["candidate_labels"] == ["cat", "dog"]
