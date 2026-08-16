"""
Unit tests for the OCR Module's deterministic orientation/skew/blur/
quality analysis (`parika.modules.ocr.image_analysis`). Uses real
Pillow/numpy against small synthetic images - never a Provider, never
Brain/Goal.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from parika.modules.ocr import image_analysis


def _stripes_image(width: int = 300, height: int = 220) -> Image.Image:
    """
    A synthetic "text-like" image: horizontal bars of *increasing*
    thickness top to bottom, so its row-projection profile is not
    vertically symmetric (0 vs 180 would otherwise always tie - see
    `detect_orientation()`'s own docstring).
    """

    image = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)
    thickness = 2
    y = 10

    while y < height - 10:
        draw.rectangle([10, y, width - 10, y + thickness], fill=0)
        y += 12
        thickness += 1

    return image.convert("RGB")


class TestOrientationDetection:
    def test_detects_correcting_rotation_for_every_quadrant(self) -> None:
        upright = _stripes_image()

        for degrees in (0, 90, 180, 270):
            rotated_input = (
                upright.rotate(degrees, expand=True) if degrees else upright
            )
            expected_correction = (360 - degrees) % 360

            result = image_analysis.detect_orientation(rotated_input)

            assert result.degrees == expected_correction

    def test_ties_deterministically_prefer_no_rotation(self) -> None:
        # A perfectly uniform image has no row-profile signal at all,
        # so every candidate ties; `0` must win deterministically.
        blank = Image.new("RGB", (100, 100), color=128)

        result = image_analysis.detect_orientation(blank)

        assert result.degrees == 0


class TestSkewCorrection:
    def test_estimate_skew_angle_recovers_small_rotation(self) -> None:
        upright = _stripes_image()
        skewed = upright.rotate(7, expand=True, fillcolor=255)

        angle = image_analysis.estimate_skew_angle(
            skewed, max_angle_degrees=15.0, step_degrees=0.5
        )

        # correct_skew must undo the +7 degree rotation, i.e. ~ -7.
        assert -8.0 <= angle <= -6.0

    def test_correct_skew_returns_zero_when_already_upright(self) -> None:
        upright = _stripes_image()

        _corrected, angle = image_analysis.correct_skew(
            upright, max_angle_degrees=15.0
        )

        assert angle == 0.0


class TestBlurDetection:
    def test_sharp_image_has_higher_variance_than_blurred(self) -> None:
        from PIL import ImageFilter

        sharp = Image.new("L", (200, 200), color=255)
        draw = ImageDraw.Draw(sharp)

        for x in range(0, 200, 10):
            draw.line([(x, 0), (x, 200)], fill=0, width=2)

        sharp_rgb = sharp.convert("RGB")
        blurred_rgb = sharp_rgb.filter(ImageFilter.GaussianBlur(radius=6))

        sharp_result = image_analysis.detect_blur(sharp_rgb)
        blurred_result = image_analysis.detect_blur(blurred_rgb)

        assert sharp_result.variance > blurred_result.variance
        assert not sharp_result.is_blurry
        assert blurred_result.is_blurry


class TestQualityScore:
    def test_low_resolution_image_is_flagged(self) -> None:
        small = Image.new("RGB", (50, 50), color=128)

        result = image_analysis.compute_quality_score(
            small, low_resolution_min_dimension=1000
        )

        assert result.is_low_resolution
        assert any("resolution" in warning for warning in result.warnings)

    def test_sharp_image_scores_higher_than_blurred_image(self) -> None:
        from PIL import ImageFilter

        sharp = Image.new("L", (1200, 1200), color=255)
        draw = ImageDraw.Draw(sharp)

        for x in range(0, 1200, 15):
            draw.line([(x, 0), (x, 1200)], fill=0, width=3)

        sharp_rgb = sharp.convert("RGB")
        blurred_rgb = sharp_rgb.filter(ImageFilter.GaussianBlur(radius=8))

        sharp_score = image_analysis.compute_quality_score(sharp_rgb)
        blurred_score = image_analysis.compute_quality_score(blurred_rgb)

        assert sharp_score.score > blurred_score.score
        assert 0.0 <= sharp_score.score <= 1.0
        assert 0.0 <= blurred_score.score <= 1.0
