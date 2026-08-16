"""
Unit tests for the Phase 5 editing ToolDrivers
(`parika.modules.vision.driver_editing`), using `FakeBrain`.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from parika.core.tool_manager.request import ToolRequest
from parika.modules.vision.driver_editing import (
    VisionCompressImageToolDriver,
    VisionConvertFormatToolDriver,
    VisionCropImageToolDriver,
    VisionEnhanceImageToolDriver,
    VisionFlipImageToolDriver,
    VisionRemoveBackgroundToolDriver,
    VisionResizeImageToolDriver,
    VisionRotateImageToolDriver,
)
from parika.modules.vision.exceptions import VisionImageReadError

from .conftest import analysis_result, read_result, write_result

cv2 = pytest.importorskip("cv2")


def _b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _source_image() -> Image.Image:
    return Image.new("RGB", (200, 100), color=(10, 20, 30))


class TestVisionCropImageToolDriver:
    def test_crops_and_writes_default_output_path(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionCropImageToolDriver(brain=fake_brain)
        response = driver.execute(
            ToolRequest(
                arguments={"path": "/img.png", "x": 0, "y": 0, "width": 50, "height": 40}
            )
        )

        assert response.result["output_path"] == "/img_cropped.png"
        assert response.result["width"] == 50
        assert response.result["height"] == 40

        write_goal = fake_brain.goals_for("filesystem.write")[0]
        assert write_goal.inputs["path"] == "/img_cropped.png"
        assert write_goal.inputs["binary"] is True

    def test_raises_when_path_missing(self, fake_brain) -> None:
        driver = VisionCropImageToolDriver(brain=fake_brain)

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={"x": 0, "y": 0, "width": 1, "height": 1}))


class TestVisionResizeImageToolDriver:
    def test_resizes_by_scale(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionResizeImageToolDriver(brain=fake_brain)
        response = driver.execute(
            ToolRequest(arguments={"path": "/img.png", "scale": 0.5})
        )

        assert response.result["width"] == 100
        assert response.result["height"] == 50


class TestVisionRotateImageToolDriver:
    def test_rotates_and_writes(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionRotateImageToolDriver(brain=fake_brain)
        response = driver.execute(
            ToolRequest(arguments={"path": "/img.png", "degrees": 90})
        )

        assert response.result["output_path"] == "/img_rotated.png"


class TestVisionFlipImageToolDriver:
    def test_flip_writes_output(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionFlipImageToolDriver(brain=fake_brain)
        response = driver.execute(
            ToolRequest(arguments={"path": "/img.png", "direction": "horizontal"})
        )

        assert response.result["output_path"] == "/img_flipped.png"

    def test_raises_on_invalid_direction(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )

        driver = VisionFlipImageToolDriver(brain=fake_brain)

        with pytest.raises(VisionImageReadError):
            driver.execute(
                ToolRequest(arguments={"path": "/img.png", "direction": "sideways"})
            )


class TestVisionEnhanceImageToolDriver:
    def test_enhances_without_calling_provider_by_default(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionEnhanceImageToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_enhance_image"
        )
        response = driver.execute(ToolRequest(arguments={"path": "/img.png"}))

        assert "notes" not in response.result
        assert fake_brain.goals_for("vision.provider_enhance_image") == []

    def test_instruction_adds_model_notes(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())
        fake_brain.queue(
            "vision.provider_enhance_image", analysis_result("Try warmer tones.")
        )

        driver = VisionEnhanceImageToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_enhance_image"
        )
        response = driver.execute(
            ToolRequest(arguments={"path": "/img.png", "instruction": "golden hour look"})
        )

        assert response.result["notes"] == "Try warmer tones."


class TestVisionRemoveBackgroundToolDriver:
    def test_writes_png_output(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionRemoveBackgroundToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_remove_background"
        )
        response = driver.execute(ToolRequest(arguments={"path": "/img.jpg"}))

        assert response.result["output_path"] == "/img_no_bg.png"


class TestVisionConvertFormatToolDriver:
    def test_converts_and_derives_output_path(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionConvertFormatToolDriver(brain=fake_brain)
        response = driver.execute(
            ToolRequest(arguments={"path": "/img.png", "target_format": "JPEG"})
        )

        assert response.result["output_path"] == "/img.jpg"
        assert response.result["format"] == "JPEG"

    def test_raises_when_target_format_missing(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_source_image())})
        )

        driver = VisionConvertFormatToolDriver(brain=fake_brain)

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={"path": "/img.png"}))


class TestVisionCompressImageToolDriver:
    def test_reports_bytes_before_and_after(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read",
            read_result({"content_base64": _b64(_source_image()), "size": 5000}),
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VisionCompressImageToolDriver(brain=fake_brain)
        response = driver.execute(ToolRequest(arguments={"path": "/img.png"}))

        assert response.result["bytes_before"] == 5000
        assert response.result["bytes_after"] > 0
        assert response.result["output_path"] == "/img_compressed.jpg"
