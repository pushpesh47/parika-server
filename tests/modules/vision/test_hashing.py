"""
Unit tests for the Vision Module's deterministic perceptual-hashing/
comparison algorithms (`parika.modules.vision.hashing`). Uses real
Pillow/numpy against small synthetic images -- never a Provider,
never Brain/Goal.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from parika.modules.vision import hashing


def _base_image() -> Image.Image:
    image = Image.new("RGB", (200, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 80, 80], fill=(0, 0, 0))
    draw.ellipse([120, 120, 180, 180], fill=(200, 30, 30))
    return image


class TestPerceptualHashes:
    def test_identical_images_have_zero_hamming_distance(self) -> None:
        image = _base_image()

        distance = hashing.hamming_distance(
            hashing.difference_hash(image), hashing.difference_hash(image.copy())
        )

        assert distance == 0

    def test_very_different_images_have_larger_hamming_distance(self) -> None:
        # Solid colors are a known aHash edge case (every cell ties
        # the image's own mean, so the hash is always 0) -- textured
        # images exercise the real comparison this hash is for.
        image_a = _base_image()
        image_b = Image.new("RGB", (200, 200), color=(255, 255, 255))
        draw = ImageDraw.Draw(image_b)
        draw.ellipse([10, 10, 190, 190], fill=(0, 0, 0))

        distance = hashing.hamming_distance(
            hashing.average_hash(image_a), hashing.average_hash(image_b)
        )

        assert distance > 0

    def test_hash_similarity_normalizes_into_unit_interval(self) -> None:
        assert hashing.hash_similarity(0, hash_size=8) == 1.0
        assert hashing.hash_similarity(64, hash_size=8) == 0.0
        assert 0.0 <= hashing.hash_similarity(10, hash_size=8) <= 1.0


class TestCompareImages:
    def test_identical_images_score_perfectly(self) -> None:
        image = _base_image()

        result = hashing.compare_images(image, image.copy())

        assert result.overall_similarity == 1.0
        assert result.perceptual_hash_distance == 0
        assert result.same_dimensions is True

    def test_visibly_different_images_score_lower(self) -> None:
        image_a = _base_image()
        image_b = image_a.copy()
        draw = ImageDraw.Draw(image_b)
        draw.rectangle([0, 0, 199, 199], fill=(10, 10, 10))

        result = hashing.compare_images(image_a, image_b)

        assert result.overall_similarity < 1.0
        assert 0.0 <= result.overall_similarity <= 1.0

    def test_different_dimensions_are_still_comparable(self) -> None:
        image_a = _base_image()
        image_b = image_a.resize((80, 80))

        result = hashing.compare_images(image_a, image_b)

        assert result.same_dimensions is False
        assert result.overall_similarity > 0.5


class TestFindDiffRegions:
    def test_locates_the_changed_region(self) -> None:
        image_a = Image.new("L", (300, 300), color=255).convert("RGB")
        image_b = image_a.copy()
        draw = ImageDraw.Draw(image_b)
        draw.rectangle([100, 100, 180, 180], fill=(0, 0, 0))

        boxes = hashing.find_diff_regions(image_a, image_b)

        assert len(boxes) >= 1
        largest = boxes[0]
        assert largest.width > 0 and largest.height > 0

    def test_identical_images_have_no_diff_regions(self) -> None:
        image = _base_image()

        boxes = hashing.find_diff_regions(image, image.copy())

        assert boxes == ()

    def test_difference_ratio_increases_with_change_area(self) -> None:
        image_a = Image.new("L", (200, 200), color=255).convert("RGB")

        small_change = image_a.copy()
        ImageDraw.Draw(small_change).rectangle([0, 0, 20, 20], fill=(0, 0, 0))

        large_change = image_a.copy()
        ImageDraw.Draw(large_change).rectangle([0, 0, 150, 150], fill=(0, 0, 0))

        small_ratio = hashing.difference_ratio(image_a, small_change)
        large_ratio = hashing.difference_ratio(image_a, large_change)

        assert small_ratio < large_ratio
