"""
PARIKA Vision Module - Deterministic Image Editing

Pure Pillow image transforms -- no model call, ever -- backing the
Phase 5 editing Capabilities (`vision.crop_image`, `vision.resize_image`,
`vision.rotate_image`, `vision.flip_image`, `vision.enhance_image`'s
deterministic default, `vision.convert_format`, `vision.compress_image`).
Mirrors `parika/modules/ocr/preprocessing.py`'s own shape (a clean,
stateless, independently testable algorithmic layer), scoped to
lightweight, classical Pillow operations only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from PIL.Image import Image

FlipDirection = Literal["horizontal", "vertical"]


def crop(image: "Image", *, x: int, y: int, width: int, height: int) -> "Image":
    """
    Crop `image` to the pixel rectangle `(x, y, x + width, y + height)`,
    clamped to the image bounds.
    """

    left = max(0, min(x, image.width))
    top = max(0, min(y, image.height))
    right = max(left, min(x + max(width, 0), image.width))
    bottom = max(top, min(y + max(height, 0), image.height))
    return image.crop((left, top, right, bottom))


def resize(
    image: "Image",
    *,
    width: int | None = None,
    height: int | None = None,
    scale: float | None = None,
    keep_aspect_ratio: bool = True,
) -> "Image":
    """
    Resize `image` via Lanczos resampling. Exactly one of `scale` or
    one/both of `width`/`height` should be given; when only one of
    `width`/`height` is given with `keep_aspect_ratio=True` (the
    default), the other dimension is derived to preserve the original
    aspect ratio.
    """

    from PIL import Image as PILImage

    if scale is not None:
        new_size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        return image.resize(new_size, PILImage.Resampling.LANCZOS)

    if width is not None and height is not None and not keep_aspect_ratio:
        new_size = (max(1, width), max(1, height))
    elif width is not None and height is None:
        ratio = width / image.width
        new_size = (max(1, width), max(1, round(image.height * ratio)))
    elif height is not None and width is None:
        ratio = height / image.height
        new_size = (max(1, round(image.width * ratio)), max(1, height))
    elif width is not None and height is not None:
        # Both given, aspect ratio preserved: fit within the box.
        ratio = min(width / image.width, height / image.height)
        new_size = (
            max(1, round(image.width * ratio)),
            max(1, round(image.height * ratio)),
        )
    else:
        return image

    return image.resize(new_size, PILImage.Resampling.LANCZOS)


def rotate(image: "Image", degrees: float, *, expand: bool = True) -> "Image":
    """Rotate `image` counter-clockwise by `degrees`, expanding the canvas by default."""

    return image.rotate(degrees, expand=expand, fillcolor=None)


def flip(image: "Image", *, direction: FlipDirection) -> "Image":
    """Flip `image` horizontally (mirror) or vertically (upside-down)."""

    from PIL import Image as PILImage

    if direction == "horizontal":
        return image.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)

    return image.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)


def enhance(
    image: "Image",
    *,
    autocontrast: bool = True,
    sharpen: bool = True,
    denoise: bool = False,
) -> "Image":
    """
    Deterministic enhancement pipeline: optional median-filter
    denoise, then auto-contrast stretch, then a mild unsharp mask --
    the same classical building blocks OCR's own
    `preprocessing.py`/`image_analysis.py` use, applied here for
    general visual enhancement rather than OCR pre-processing.
    """

    from PIL import ImageFilter, ImageOps

    result = image.convert("RGB")

    if denoise:
        result = result.filter(ImageFilter.MedianFilter(size=3))

    if autocontrast:
        result = ImageOps.autocontrast(result)

    if sharpen:
        result = result.filter(ImageFilter.UnsharpMask(radius=2, percent=100))

    return result


def convert_format(image: "Image", target_format: str) -> "Image":
    """
    Prepare `image` for saving as `target_format`: flattens
    transparency onto a white background for formats without alpha
    support (JPEG/BMP), leaves it unchanged otherwise. The actual
    save/encode happens via `engine.encode_image_base64(...,
    image_format=target_format)`.
    """

    normalized = target_format.strip().upper()

    if normalized in ("JPEG", "JPG", "BMP") and image.mode in ("RGBA", "LA", "P"):
        from PIL import Image as PILImage

        background = PILImage.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        return background

    return image
