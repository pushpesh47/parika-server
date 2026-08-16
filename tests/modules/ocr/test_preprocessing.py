"""
Unit tests for the OCR Module's deterministic image decode/encode and
enhancement algorithms (`parika.modules.ocr.preprocessing`). Uses real
Pillow/numpy against small synthetic images - never a Provider, never
Brain/Goal. Orientation/skew/blur/quality tests live in
`test_image_analysis.py`; table-region detection tests live in
`test_table_detection.py` - mirroring the source-level split.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from parika.modules.ocr import preprocessing


class TestDecodeEncodeCropRoundTrip:
    def test_decode_encode_round_trip_preserves_pixels(self) -> None:
        original = Image.new("RGB", (64, 64), color=(10, 20, 30))
        raw = preprocessing.encode_image(original)
        decoded = preprocessing.decode_image(raw)

        assert decoded.size == (64, 64)
        assert decoded.convert("RGB").getpixel((0, 0)) == (10, 20, 30)

    def test_crop_region_extracts_expected_pixels(self) -> None:
        image = Image.new("RGB", (200, 200), color=(255, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle([50, 50, 100, 100], fill=(0, 255, 0))

        cropped = preprocessing.crop_region(image, x=50, y=50, width=50, height=50)

        assert cropped.size == (50, 50)
        assert cropped.getpixel((5, 5)) == (0, 255, 0)

    def test_crop_region_clamps_out_of_bounds_rectangle(self) -> None:
        image = Image.new("RGB", (100, 100), color=(1, 2, 3))

        cropped = preprocessing.crop_region(image, x=90, y=90, width=1000, height=1000)

        assert cropped.size == (10, 10)


class TestContrastDenoiseUpscale:
    def test_enhance_contrast_returns_grayscale_image(self) -> None:
        image = Image.new("RGB", (50, 50), color=(100, 100, 100))

        result = preprocessing.enhance_contrast(image)

        assert result.mode == "L"

    def test_denoise_preserves_image_size(self) -> None:
        image = Image.new("RGB", (60, 60), color=(1, 2, 3))

        result = preprocessing.denoise(image)

        assert result.size == (60, 60)

    def test_upscale_if_low_resolution_upscales_below_threshold(self) -> None:
        small = Image.new("RGB", (300, 200), color=200)

        upscaled, was_upscaled = preprocessing.upscale_if_low_resolution(
            small, min_dimension=1000
        )

        assert was_upscaled
        assert min(upscaled.size) >= 1000

    def test_upscale_if_low_resolution_leaves_large_image_unchanged(self) -> None:
        large = Image.new("RGB", (2000, 1500), color=200)

        result, was_upscaled = preprocessing.upscale_if_low_resolution(
            large, min_dimension=1000
        )

        assert not was_upscaled
        assert result.size == (2000, 1500)


class TestPreprocessForRecognition:
    def test_pipeline_reports_every_step_applied(self) -> None:
        small = Image.new("RGB", (300, 200), color=200)

        result_image, report = preprocessing.preprocess_for_recognition(
            small, low_resolution_min_dimension=1000
        )

        assert report.denoised
        assert report.contrast_enhanced
        assert report.upscaled
        assert min(result_image.size) >= 1000

    def test_pipeline_can_disable_denoise_and_contrast(self) -> None:
        small = Image.new("RGB", (300, 200), color=200)

        _result_image, report = preprocessing.preprocess_for_recognition(
            small,
            low_resolution_min_dimension=100,
            denoise_enabled=False,
            contrast_enabled=False,
        )

        assert not report.denoised
        assert not report.contrast_enhanced
