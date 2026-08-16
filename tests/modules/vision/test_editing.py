"""
Unit tests for the Vision Module's deterministic Pillow-based image
editing transforms (`parika.modules.vision.editing`).
"""

from __future__ import annotations

from PIL import Image

from parika.modules.vision import editing


def _image(size: tuple[int, int] = (200, 100), mode: str = "RGBA") -> Image.Image:
    return Image.new(mode, size, color=(10, 20, 30, 255))


class TestCrop:
    def test_crops_to_the_requested_rectangle(self) -> None:
        cropped = editing.crop(_image(), x=10, y=10, width=50, height=40)
        assert cropped.size == (50, 40)

    def test_clamps_out_of_bounds_rectangle(self) -> None:
        cropped = editing.crop(_image((100, 100)), x=90, y=90, width=50, height=50)
        assert cropped.size == (10, 10)


class TestResize:
    def test_width_only_preserves_aspect_ratio(self) -> None:
        resized = editing.resize(_image((200, 100)), width=100)
        assert resized.size == (100, 50)

    def test_scale_factor(self) -> None:
        resized = editing.resize(_image((200, 100)), scale=0.5)
        assert resized.size == (100, 50)

    def test_both_dimensions_without_aspect_ratio(self) -> None:
        resized = editing.resize(
            _image((200, 100)), width=50, height=50, keep_aspect_ratio=False
        )
        assert resized.size == (50, 50)

    def test_both_dimensions_with_aspect_ratio_fits_within_box(self) -> None:
        resized = editing.resize(_image((200, 100)), width=50, height=50)
        assert resized.width <= 50 and resized.height <= 50


class TestRotateAndFlip:
    def test_rotate_expands_canvas_by_default(self) -> None:
        rotated = editing.rotate(_image((200, 100)), 45)
        assert rotated.width > 200 or rotated.height > 100

    def test_flip_horizontal_preserves_size(self) -> None:
        flipped = editing.flip(_image((200, 100)), direction="horizontal")
        assert flipped.size == (200, 100)

    def test_flip_vertical_preserves_size(self) -> None:
        flipped = editing.flip(_image((200, 100)), direction="vertical")
        assert flipped.size == (200, 100)


class TestEnhance:
    def test_returns_rgb_image_of_same_size(self) -> None:
        enhanced = editing.enhance(_image().convert("RGB"))
        assert enhanced.mode == "RGB"
        assert enhanced.size == (200, 100)


class TestConvertFormat:
    def test_flattens_alpha_for_jpeg(self) -> None:
        converted = editing.convert_format(_image(), "JPEG")
        assert converted.mode == "RGB"

    def test_leaves_png_unchanged(self) -> None:
        image = _image()
        converted = editing.convert_format(image, "PNG")
        assert converted.mode == image.mode
