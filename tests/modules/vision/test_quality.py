"""
Unit tests for the Vision Module's deterministic blur/rotation/
quality/anomaly analysis (`parika.modules.vision.quality`). Uses real
Pillow/numpy against small synthetic images -- never a Provider,
never Brain/Goal. Mirrors `tests/modules/ocr/test_image_analysis.py`'s
own synthetic-image shape.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from parika.modules.vision import quality


def _stripes_image(width: int = 300, height: int = 220) -> Image.Image:
    """Horizontal bars of increasing thickness -- a strongly banded,
    non-vertically-symmetric row-projection profile."""

    image = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)
    thickness = 2
    y = 10

    while y < height - 10:
        draw.rectangle([10, y, width - 10, y + thickness], fill=0)
        y += 12
        thickness += 1

    return image.convert("RGB")


class TestDetectRotation:
    def test_detects_correcting_rotation_for_every_quadrant(self) -> None:
        upright = _stripes_image()

        for degrees in (0, 90, 180, 270):
            rotated_input = (
                upright.rotate(degrees, expand=True) if degrees else upright
            )
            expected_correction = (360 - degrees) % 360

            result = quality.detect_rotation(rotated_input)

            assert result.degrees == expected_correction

    def test_ties_deterministically_prefer_no_rotation(self) -> None:
        blank = Image.new("RGB", (100, 100), color=128)

        result = quality.detect_rotation(blank)

        assert result.degrees == 0


class TestDetectBlur:
    def test_sharp_image_has_higher_variance_than_blurred(self) -> None:
        sharp = Image.new("L", (200, 200), color=255)
        draw = ImageDraw.Draw(sharp)

        for x in range(0, 200, 10):
            draw.line([(x, 0), (x, 200)], fill=0, width=2)

        sharp_rgb = sharp.convert("RGB")
        blurred_rgb = sharp_rgb.filter(ImageFilter.GaussianBlur(radius=6))

        sharp_result = quality.detect_blur(sharp_rgb)
        blurred_result = quality.detect_blur(blurred_rgb)

        assert sharp_result.variance > blurred_result.variance
        assert not sharp_result.is_blurry
        assert blurred_result.is_blurry


class TestComputeQualityScore:
    def test_low_resolution_image_is_flagged(self) -> None:
        small = Image.new("RGB", (50, 50), color=128)

        result = quality.compute_quality_score(
            small, low_resolution_min_dimension=1000
        )

        assert result.is_low_resolution
        assert any("resolution" in warning for warning in result.warnings)

    def test_sharp_image_scores_higher_than_blurred_image(self) -> None:
        sharp = Image.new("L", (1200, 1200), color=255)
        draw = ImageDraw.Draw(sharp)

        for x in range(0, 1200, 15):
            draw.line([(x, 0), (x, 1200)], fill=0, width=3)

        sharp_rgb = sharp.convert("RGB")
        blurred_rgb = sharp_rgb.filter(ImageFilter.GaussianBlur(radius=8))

        sharp_score = quality.compute_quality_score(sharp_rgb)
        blurred_score = quality.compute_quality_score(blurred_rgb)

        assert sharp_score.score > blurred_score.score
        assert 0.0 <= sharp_score.score <= 1.0
        assert 0.0 <= blurred_score.score <= 1.0


class TestDetectAnomalousRegions:
    def test_flags_a_locally_bright_outlier_region(self) -> None:
        image = Image.new("L", (240, 240), color=128)
        draw = ImageDraw.Draw(image)
        draw.rectangle([200, 200, 235, 235], fill=250)

        result = quality.detect_anomalous_regions(image.convert("RGB"), grid=8)

        assert result.has_anomalies
        assert result.regions
        assert 0.0 <= result.anomaly_score <= 1.0

    def test_uniform_image_has_no_anomalies(self) -> None:
        image = Image.new("RGB", (200, 200), color=(128, 128, 128))

        result = quality.detect_anomalous_regions(image, grid=8)

        assert not result.has_anomalies
        assert result.regions == ()
