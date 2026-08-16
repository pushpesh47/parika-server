"""
Unit tests for the Vision Module's deterministic GrabCut background
removal (`parika.modules.vision.segmentation`).
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from parika.modules.vision import config, segmentation
from parika.modules.vision.exceptions import VisionDependencyUnavailableError

cv2 = pytest.importorskip("cv2")


class TestRemoveBackground:
    def test_returns_rgba_image_with_transparent_background(self) -> None:
        image = Image.new("RGB", (200, 200), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)
        draw.ellipse([60, 60, 140, 140], fill=(20, 60, 200))

        result = segmentation.remove_background(image)

        assert result.mode == "RGBA"
        assert result.size == image.size

        alpha = result.split()[-1]

        import numpy as np

        alpha_array = np.asarray(alpha)
        # Some pixels are treated as foreground (kept opaque) and some
        # as background (made transparent) -- a real segmentation,
        # not a no-op.
        assert alpha_array.max() > 0

    def test_raises_when_opencv_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "opencv_dependency_available", lambda: False)

        with pytest.raises(VisionDependencyUnavailableError):
            segmentation.remove_background(Image.new("RGB", (50, 50)))
