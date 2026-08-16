"""
Unit tests for `VisionDetectFacesToolDriver`/`VisionDetectQrCodesToolDriver`/
`VisionDetectBarcodesToolDriver` (`parika.modules.vision.driver_detection`),
using `FakeBrain`.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from parika.core.tool_manager.request import ToolRequest
from parika.modules.vision.driver_detection import (
    VisionDetectBarcodesToolDriver,
    VisionDetectFacesToolDriver,
    VisionDetectQrCodesToolDriver,
)
from parika.modules.vision.exceptions import VisionImageReadError

from .conftest import analysis_result, read_result

qrcode = pytest.importorskip("qrcode")


def _b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class TestVisionDetectFacesToolDriver:
    def test_returns_zero_faces_without_calling_provider(self, fake_brain) -> None:
        blank = Image.new("RGB", (100, 100), color=(200, 200, 200))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(blank)}))

        driver = VisionDetectFacesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_faces"
        )

        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["count"] == 0
        assert fake_brain.goals_for("vision.provider_detect_faces") == []

    def test_calls_provider_only_when_instruction_given(self, fake_brain) -> None:
        blank = Image.new("RGB", (100, 100), color=(200, 200, 200))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(blank)}))
        fake_brain.queue(
            "vision.provider_detect_faces", analysis_result("No people visible.")
        )

        driver = VisionDetectFacesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_faces"
        )

        response = driver.execute(
            ToolRequest(arguments={"path": "/a.png", "instruction": "describe them"})
        )

        assert response.result["explanation"] == "No people visible."

    def test_raises_when_path_missing(self, fake_brain) -> None:
        driver = VisionDetectFacesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_faces"
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={}))


class TestVisionDetectQrCodesToolDriver:
    def test_decodes_a_real_qr_code(self, fake_brain) -> None:
        image = qrcode.make("hello-parika").convert("RGB")
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))

        driver = VisionDetectQrCodesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_qr_codes"
        )

        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["count"] == 1
        assert response.result["codes"][0]["data"] == "hello-parika"


class TestVisionDetectBarcodesToolDriver:
    def test_returns_zero_codes_for_a_qr_only_image(self, fake_brain) -> None:
        image = qrcode.make("not a barcode").convert("RGB")
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))

        driver = VisionDetectBarcodesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_detect_barcodes"
        )

        response = driver.execute(ToolRequest(arguments={"path": "/a.png"}))

        assert response.result["count"] == 0
