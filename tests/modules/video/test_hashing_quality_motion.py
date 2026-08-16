"""
Unit tests for the Video Module's deterministic per-frame algorithms
(`hashing.py`, `quality.py`, `motion.py`, `regions.py`) -- pure
Pillow/numpy, no Brain/Goal/filesystem involved.
"""

from __future__ import annotations

import pytest

pytest.importorskip("numpy")
from PIL import Image

from parika.modules.video import hashing, motion, quality, regions


def _solid_image(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> Image.Image:
    return Image.new("RGB", size, color=color)


class TestHashing:
    def test_identical_images_have_zero_change_score(self) -> None:
        image = _solid_image((100, 150, 200))

        score = hashing.change_score(image, image)

        assert score.overall == 0.0
        assert score.hash_distance_ratio == 0.0

    def test_very_different_images_have_high_change_score(self) -> None:
        black = _solid_image((0, 0, 0))
        white = _solid_image((255, 255, 255))

        score = hashing.change_score(black, white)

        assert score.overall >= 0.5

    def test_find_diff_regions_detects_no_regions_for_identical_images(self) -> None:
        image = _solid_image((10, 20, 30))

        boxes = hashing.find_diff_regions(image, image)

        assert boxes == ()

    def test_pixel_similarity_is_one_for_identical_images(self) -> None:
        image = _solid_image((10, 20, 30))

        assert hashing.pixel_similarity(image, image) == 1.0


class TestQuality:
    def test_solid_color_image_has_low_laplacian_variance(self) -> None:
        image = _solid_image((128, 128, 128))

        result = quality.detect_blur(image, threshold=100.0)

        assert result.variance == 0.0
        assert result.is_blurry is True

    def test_black_image_is_detected_as_black_frame(self) -> None:
        image = _solid_image((0, 0, 0))

        result = quality.detect_black_frame(image, threshold=16.0)

        assert result.is_black is True
        assert result.mean_brightness == 0.0

    def test_bright_image_is_not_a_black_frame(self) -> None:
        image = _solid_image((200, 200, 200))

        result = quality.detect_black_frame(image, threshold=16.0)

        assert result.is_black is False

    def test_detect_rotation_returns_a_valid_candidate(self) -> None:
        image = _solid_image((100, 100, 100))

        result = quality.detect_rotation(image)

        assert result.degrees in (0, 90, 180, 270)
        assert 0.0 <= result.confidence <= 1.0


class TestMotion:
    def test_identical_frames_have_no_motion(self) -> None:
        image = _solid_image((50, 50, 50))

        result = motion.detect_motion(image, image)

        assert result.has_motion is False
        assert result.changed_pixel_ratio == 0.0
        assert result.regions == ()

    def test_localized_change_is_detected_as_motion_region(self) -> None:
        import numpy as np

        base = np.zeros((64, 64, 3), dtype="uint8")
        previous = Image.fromarray(base)

        changed = base.copy()
        changed[20:40, 20:40] = 255
        current = Image.fromarray(changed)

        result = motion.detect_motion(previous, current, area_ratio_threshold=0.01)

        assert result.has_motion is True
        assert len(result.regions) >= 1


class TestRegions:
    def test_label_regions_finds_a_single_connected_block(self) -> None:
        import numpy as np

        mask = np.zeros((20, 20), dtype=bool)
        mask[5:10, 5:10] = True

        boxes = regions.label_regions(mask, min_area=1)

        assert len(boxes) == 1
        assert boxes[0].width == 5
        assert boxes[0].height == 5

    def test_label_regions_filters_by_min_area(self) -> None:
        import numpy as np

        mask = np.zeros((20, 20), dtype=bool)
        mask[0, 0] = True  # single-pixel region

        boxes = regions.label_regions(mask, min_area=5)

        assert boxes == ()
