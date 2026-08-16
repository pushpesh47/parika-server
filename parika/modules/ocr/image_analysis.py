"""
PARIKA OCR Module - Deterministic Orientation, Skew, Blur & Quality Analysis

Split out of `preprocessing.py` purely to keep that file within the
project's File Size Guidelines (`docs/architecture/
PARIKA_Core_Coding_Standards.md`) - orientation/skew estimation and
blur/quality scoring are already a cohesive, independently testable
group (all built on the same row-projection-profile and variance-of-
Laplacian techniques), used by `analysis_driver.py`
(`ocr.detect_orientation`/`ocr.detect_quality`) and by
`preprocessing.preprocess_for_recognition()`.

Requires the optional `Pillow`/`numpy` dependency pair, exactly like
the rest of `preprocessing.py`; raises `OcrDependencyUnavailableError`
when unavailable. See `preprocessing.py`'s own module docstring for
this module's one honest, documented limitation
(`detect_orientation()`'s 0-vs-180 ambiguity).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .config import require_imaging

if TYPE_CHECKING:
    import numpy as np
    from PIL.Image import Image

DEFAULT_MAX_DESKEW_ANGLE_DEGREES = 15.0
DEFAULT_LOW_RESOLUTION_MIN_DIMENSION = 1000
DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0

_ORIENTATION_CANDIDATES = (0, 90, 180, 270)
_LAPLACIAN_KERNEL_CENTER = -4.0


@dataclass(frozen=True, slots=True, kw_only=True)
class OrientationResult:
    """Best-effort gross page rotation guess - see `detect_orientation()`."""

    degrees: int
    confidence: float
    exif_corrected: bool


def detect_orientation(
    image: "Image", *, exif_corrected: bool = False
) -> OrientationResult:
    """
    Best-effort, deterministic guess of `image`'s gross page rotation
    (one of 0/90/180/270 degrees), via the classical projection-
    profile heuristic: a correctly-oriented page of text produces a
    strongly "peaky" (high-variance) horizontal row-darkness profile,
    from the regular horizontal bands text lines create, whereas the
    same page rotated 90 degrees loses that banding. `degrees` is the
    `PIL.Image.rotate()` angle that would correct the input.

    This is a real, lightweight, long-standing technique, but - absent
    a trained Orientation and Script Detection (OSD) model such as
    Tesseract's - it is meaningfully less reliable, especially for
    sparse or non-text-heavy images. `confidence` reflects only the
    internal margin between the best and second-best candidate
    rotation, not a calibrated probability; treat a low value as "not
    conclusive" rather than "wrong".

    Portrait-vs-landscape (0/180 vs 90/270) is reliably distinguished,
    since rotating by 90 degrees genuinely changes the row-projection
    profile's periodicity. Upright-vs-upside-down (0 vs 180) is
    mathematically the hard case for this specific metric: reversing
    an image vertically only reverses its row order, which variance is
    invariant to, so 0 and 180 frequently score identically. On such a
    tie, `0` (no rotation) is deterministically preferred over `180` -
    a sensible prior, not a detection - and `confidence` correctly
    reports that near-zero margin rather than a false positive.
    """

    require_imaging()

    import numpy as np

    grayscale = image.convert("L")
    grayscale.thumbnail((400, 400))

    scores: dict[int, float] = {}

    for degrees in _ORIENTATION_CANDIDATES:
        rotated = grayscale.rotate(degrees, expand=True) if degrees else grayscale
        array = np.asarray(rotated, dtype=np.float64)
        row_profile = array.mean(axis=1)
        scores[degrees] = float(row_profile.var())

    # Sorted ascending by *negated* score, not `reverse=True`: a
    # plain descending sort via `reverse=True` on a stable sort also
    # reverses the relative order of tied entries, which would make
    # `180` beat `0` (and `270` beat `90`) on an exact tie - the
    # opposite of the sensible prior "prefer no rotation on truly
    # ambiguous evidence". Negating the key keeps ties in their
    # original, canonical `_ORIENTATION_CANDIDATES` order instead.
    ordered = sorted(scores.items(), key=lambda item: -item[1])
    best_degrees, best_score = ordered[0]
    total = sum(score for _, score in ordered) or 1.0
    margin = (best_score - ordered[1][1]) / total if len(ordered) > 1 else 1.0

    return OrientationResult(
        degrees=best_degrees,
        confidence=round(max(0.0, min(1.0, margin)), 4),
        exif_corrected=exif_corrected,
    )


def estimate_skew_angle(
    image: "Image",
    *,
    max_angle_degrees: float = DEFAULT_MAX_DESKEW_ANGLE_DEGREES,
    step_degrees: float = 0.5,
) -> float:
    """
    Estimate a scanned page's small skew angle (within
    +/-`max_angle_degrees`), via the same projection-profile principle
    `detect_orientation()` uses at whole-quadrant granularity: the
    rotation angle that maximizes the horizontal projection profile's
    variance is the one that best aligns text lines to the horizontal
    axis. Runs against a downscaled copy purely for speed; the
    returned angle is resolution-independent.
    """

    require_imaging()

    import numpy as np

    grayscale = image.convert("L")
    grayscale.thumbnail((600, 600))

    best_angle = 0.0
    best_variance = -1.0

    angle = -max_angle_degrees
    while angle <= max_angle_degrees + 1e-9:
        rotated = grayscale.rotate(angle, expand=True, fillcolor=255)
        array = np.asarray(rotated, dtype=np.float64)
        variance = float(array.mean(axis=1).var())

        if variance > best_variance:
            best_variance = variance
            best_angle = angle

        angle += step_degrees

    return round(best_angle, 2)


def correct_skew(
    image: "Image", *, max_angle_degrees: float = DEFAULT_MAX_DESKEW_ANGLE_DEGREES
) -> tuple["Image", float]:
    """
    Rotate `image` by its own estimated skew angle (see
    `estimate_skew_angle()`). Returns `(corrected_image, angle_applied)`;
    `angle_applied == 0.0` leaves `image` unchanged (never re-encoded).
    """

    require_imaging()

    angle = estimate_skew_angle(image, max_angle_degrees=max_angle_degrees)

    if angle == 0.0:
        return image, 0.0

    from PIL import Image as PILImage

    corrected = image.rotate(
        angle, expand=True, fillcolor=255, resample=PILImage.Resampling.BICUBIC
    )
    return corrected, angle


def _laplacian_variance(array: "np.ndarray") -> float:
    """
    Classical "variance of Laplacian" sharpness metric, computed via a
    simple 3x3 discrete Laplacian convolution (edge-padded, valid
    everywhere) - no `scipy`/`opencv` dependency required.
    """

    import numpy as np

    padded = np.pad(array, 1, mode="edge")
    response = (
        padded[0:-2, 1:-1]
        + padded[1:-1, 0:-2]
        + _LAPLACIAN_KERNEL_CENTER * padded[1:-1, 1:-1]
        + padded[1:-1, 2:]
        + padded[2:, 1:-1]
    )
    return float(response.var())


@dataclass(frozen=True, slots=True, kw_only=True)
class BlurResult:
    """Sharpness measurement - see `detect_blur()`."""

    variance: float
    is_blurry: bool


def detect_blur(
    image: "Image", *, threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD
) -> BlurResult:
    """
    Classical "variance of Laplacian" blur metric: a sharp image has
    strong, varied edges (high-variance Laplacian response); a blurry
    one's edges are smoothed out (low variance). `threshold` is an
    empirical cutoff - tunable via `[ocr].blur_variance_threshold` -
    not a universal constant; it depends on image resolution and
    content.
    """

    require_imaging()

    import numpy as np

    array = np.asarray(image.convert("L"), dtype=np.float64)
    variance = _laplacian_variance(array)

    return BlurResult(variance=round(variance, 2), is_blurry=variance < threshold)


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityWeights:
    """Relative importance of each quality dimension, in [0, 1] each, summing to 1.0."""

    resolution_weight: float = 0.35
    sharpness_weight: float = 0.35
    contrast_weight: float = 0.15
    brightness_weight: float = 0.15


DEFAULT_QUALITY_WEIGHTS = QualityWeights()


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityResult:
    """Composite document-image quality assessment - see `compute_quality_score()`."""

    score: float
    width: int
    height: int
    blur_variance: float
    is_blurry: bool
    contrast: float
    brightness: float
    is_low_resolution: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def compute_quality_score(
    image: "Image",
    *,
    blur_threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD,
    low_resolution_min_dimension: int = DEFAULT_LOW_RESOLUTION_MIN_DIMENSION,
    weights: QualityWeights = DEFAULT_QUALITY_WEIGHTS,
) -> QualityResult:
    """
    Composite, deterministic document-image quality score in `[0, 1]`,
    combining resolution, sharpness (blur variance), and contrast/
    brightness - the same factors that most affect whether recognition
    will succeed. A low score does not guarantee recognition will
    fail, and a high one does not guarantee it will succeed; treat
    this as an inexpensive triage signal computed without any model
    call, not a correctness guarantee.
    """

    require_imaging()

    import numpy as np

    array = np.asarray(image.convert("L"), dtype=np.float64)
    blur = detect_blur(image, threshold=blur_threshold)

    width, height = image.size
    is_low_resolution = min(width, height) < low_resolution_min_dimension
    contrast = float(array.std())
    brightness = float(array.mean())

    resolution_component = 0.0 if is_low_resolution else 1.0
    sharpness_component = (
        min(1.0, blur.variance / (blur_threshold * 2)) if blur_threshold > 0 else 1.0
    )
    contrast_component = min(1.0, contrast / 64.0)
    brightness_component = max(0.0, 1.0 - abs(brightness - 128.0) / 128.0)

    score = (
        weights.resolution_weight * resolution_component
        + weights.sharpness_weight * sharpness_component
        + weights.contrast_weight * contrast_component
        + weights.brightness_weight * brightness_component
    )

    warnings: list[str] = []

    if is_low_resolution:
        warnings.append(
            "Image resolution is low; recognition accuracy may be reduced."
        )

    if blur.is_blurry:
        warnings.append("Image appears blurry; recognition accuracy may be reduced.")

    if contrast_component < 0.3:
        warnings.append(
            "Image has low contrast; recognition accuracy may be reduced."
        )

    return QualityResult(
        score=round(max(0.0, min(1.0, score)), 4),
        width=width,
        height=height,
        blur_variance=blur.variance,
        is_blurry=blur.is_blurry,
        contrast=round(contrast, 2),
        brightness=round(brightness, 2),
        is_low_resolution=is_low_resolution,
        warnings=tuple(warnings),
    )
