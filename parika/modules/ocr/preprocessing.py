"""
PARIKA OCR Module - Deterministic Image Decode/Encode & Enhancement

Pure, stateless, deterministic image algorithms - no model call, no
filesystem access, no Brain/Goal/Capability concept. Mirrors
`parika/tools/web_search/ranking.py`/`dedup.py`'s own shape: a clean,
independently testable algorithmic layer that the OCR Module's
ToolDrivers (`analysis_driver.py`, `text_tools_driver.py`, `driver.py`)
call, never the other way around.

Covers basic image I/O (`decode_image()`/`encode_image()`/
`crop_region()`) and the enhancement steps
`preprocess_for_recognition()` chains together (contrast/denoise/
upscale, plus skew correction via the sibling `image_analysis.py`
module). Orientation/skew estimation and blur/quality scoring live in
`image_analysis.py`; table-region detection lives in
`table_detection.py` - both split out purely to keep this file within
the project's File Size Guidelines
(`docs/architecture/PARIKA_Core_Coding_Standards.md`).

Every function below requires the optional `Pillow`/`numpy` dependency
pair (`pyproject.toml`'s `ocr` extra) and raises
`OcrDependencyUnavailableError` when it is not installed - exactly the
same gracefully-degrading contract
`parika/tools/coding/analyzers/tree_sitter_analyzer.py` already
establishes for its own optional dependency. Callers should check
`config.imaging_dependency_available()` (or
`OcrToolConfig.imaging_available`) first to decide whether to offer
these capabilities at all, rather than relying on the exception for
ordinary control flow.

Deliberately scoped to lightweight, classical techniques - never a
trained model, matching the "prefer lightweight computer vision
algorithms over LLMs" requirement. True document-boundary detection
and full perspective correction (unwarping a photographed page) need
contour/corner finding, a substantially different, heavier algorithmic
problem than anything in this Module; intentionally not implemented
here (see the OCR Module's own recommended-extensions notes) rather
than shipped as an unreliable approximation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import require_imaging, require_pillow
from .image_analysis import correct_skew

if TYPE_CHECKING:
    from PIL.Image import Image

DEFAULT_MAX_DESKEW_ANGLE_DEGREES = 15.0
DEFAULT_LOW_RESOLUTION_MIN_DIMENSION = 1000
DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0


def decode_image(image_bytes: bytes) -> "Image":
    """
    Decode raw image bytes into a Pillow `Image`, applying its own
    EXIF orientation tag (if any) so a photo taken with a rotated
    camera is already upright before any further analysis - a real,
    zero-cost rotation correction, distinct from `detect_orientation()`
    /`correct_skew()`'s heuristics below (which handle scans that carry
    no EXIF data at all).
    """

    require_pillow()

    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(image_bytes))
    image.load()
    return ImageOps.exif_transpose(image)


def encode_image(image: "Image", *, image_format: str = "PNG") -> bytes:
    """Encode a Pillow `Image` back to raw bytes for re-transmission."""

    require_pillow()

    buffer = io.BytesIO()
    to_save = image.convert("RGB") if image_format.upper() == "JPEG" else image
    to_save.save(buffer, format=image_format)
    return buffer.getvalue()


def crop_region(
    image: "Image", *, x: int, y: int, width: int, height: int
) -> "Image":
    """
    Crop `image` to the pixel rectangle `(x, y, x + width, y + height)`,
    clamped to the image bounds, for region-specific OCR - sending
    only the relevant pixels to a Provider model reduces both the
    image size and the tokens/latency the recognition call costs.
    """

    require_pillow()

    left = max(0, min(x, image.width))
    top = max(0, min(y, image.height))
    right = max(left, min(x + max(width, 0), image.width))
    bottom = max(top, min(y + max(height, 0), image.height))
    return image.crop((left, top, right, bottom))


def enhance_contrast(image: "Image") -> "Image":
    """Auto-contrast stretch (`PIL.ImageOps.autocontrast`) - lightweight, deterministic."""

    require_pillow()

    from PIL import ImageOps

    return ImageOps.autocontrast(image.convert("L"))


def denoise(image: "Image") -> "Image":
    """Median-filter denoise - effective against scanner speckle noise."""

    require_pillow()

    from PIL import ImageFilter

    return image.filter(ImageFilter.MedianFilter(size=3))


def upscale_if_low_resolution(
    image: "Image", *, min_dimension: int = DEFAULT_LOW_RESOLUTION_MIN_DIMENSION
) -> tuple["Image", bool]:
    """
    Lanczos-resample upscale when `image`'s shorter side is below
    `min_dimension` - simple interpolation, not a trained super-
    resolution model, but a real, cheap improvement for genuinely
    low-resolution scans/photos.
    """

    require_pillow()

    shorter_side = min(image.width, image.height)

    if shorter_side >= min_dimension or shorter_side <= 0:
        return image, False

    from PIL import Image as PILImage

    scale = min_dimension / shorter_side
    new_size = (round(image.width * scale), round(image.height * scale))
    return image.resize(new_size, PILImage.Resampling.LANCZOS), True


@dataclass(frozen=True, slots=True, kw_only=True)
class PreprocessingReport:
    """What `preprocess_for_recognition()` actually applied, for the response's `attributes`."""

    skew_angle_corrected: float
    denoised: bool
    contrast_enhanced: bool
    upscaled: bool


def preprocess_for_recognition(
    image: "Image",
    *,
    max_deskew_angle_degrees: float = DEFAULT_MAX_DESKEW_ANGLE_DEGREES,
    low_resolution_min_dimension: int = DEFAULT_LOW_RESOLUTION_MIN_DIMENSION,
    denoise_enabled: bool = True,
    contrast_enabled: bool = True,
) -> tuple["Image", PreprocessingReport]:
    """
    Run the ordered preprocessing pipeline the spec requires (deskew ->
    denoise -> contrast -> upscale), once, and return both the result
    and a report of exactly what was applied - composable by any
    caller that then hands the *same* returned image to
    `ocr.provider_extract_text`, never a second, redundant
    preprocessing pass.
    """

    require_imaging()

    corrected, angle = correct_skew(image, max_angle_degrees=max_deskew_angle_degrees)

    if denoise_enabled:
        corrected = denoise(corrected)

    if contrast_enabled:
        corrected = enhance_contrast(corrected)

    corrected, upscaled = upscale_if_low_resolution(
        corrected, min_dimension=low_resolution_min_dimension
    )

    report = PreprocessingReport(
        skew_angle_corrected=angle,
        denoised=denoise_enabled,
        contrast_enhanced=contrast_enabled,
        upscaled=upscaled,
    )
    return corrected, report


# Otsu-threshold-based table-region detection (`TableRegion`,
# `detect_table_regions()`) lives in `table_detection.py` - split out
# purely to keep this file within the project's File Size Guidelines;
# see that module's own docstring.
