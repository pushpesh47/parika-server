"""
PARIKA Vision Module - Deterministic Blur, Rotation, Quality & Anomaly Analysis

Pure Pillow/numpy image algorithms -- no model call, no filesystem
access, no Brain/Goal/Capability concept -- deliberately mirroring
`parika/modules/ocr/image_analysis.py`'s own projection-profile
(orientation) and variance-of-Laplacian (blur) techniques, but kept
fully self-contained within this Module rather than importing OCR's
implementation, since Modules in this codebase never depend on one
another's internals (`document.extract_text` reuses OCR only through
its public `ocr.extract_text` *Capability*, via a `Goal`, never a
direct Python import -- see `parika/modules/document/engine.py`).

Backs `vision.detect_blur`, `vision.detect_rotation`,
`vision.analyze_image_quality`, and `vision.detect_anomalies`: every
one of these Capabilities' *default* result is 100% deterministic --
zero model calls, zero Provider cost -- exactly the "prefer
deterministic computer vision algorithms before invoking a Vision
Language Model" requirement. Each Capability's own Provider-backed
`vision.provider_*` Capability (registered for naming-convention/
architecture consistency with every other new Capability in this
Module) is only ever consulted by its ToolDriver when the caller
explicitly asks for a semantic explanation on top of the already-
computed deterministic metrics -- never to compute the metrics
themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import regions

if TYPE_CHECKING:
    import numpy as np
    from PIL.Image import Image

_ORIENTATION_CANDIDATES = (0, 90, 180, 270)
_LAPLACIAN_KERNEL_CENTER = -4.0

DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0
DEFAULT_LOW_RESOLUTION_MIN_DIMENSION = 1000
DEFAULT_ANOMALY_GRID = 8
DEFAULT_ANOMALY_Z_THRESHOLD = 2.5


@dataclass(frozen=True, slots=True, kw_only=True)
class RotationResult:
    """Best-effort gross page/photo rotation guess -- see `detect_rotation()`."""

    degrees: int
    confidence: float


def detect_rotation(image: "Image") -> RotationResult:
    """
    Best-effort, deterministic guess of `image`'s gross rotation (one
    of 0/90/180/270 degrees), via the classical row-projection-profile
    heuristic: the correctly-oriented reading of an image with any
    directional structure (text lines, a horizon, architectural
    lines) produces a "peakier" (higher-variance) horizontal row-
    darkness profile than the same image rotated 90 degrees.
    `degrees` is the correcting rotation angle. Portrait-vs-landscape
    is reliably distinguished; upright-vs-upside-down (0 vs 180) is
    this metric's known hard case (row-variance is reversal-
    invariant) -- on a tie, `0` is deterministically preferred, and
    `confidence` honestly reports the resulting near-zero margin
    rather than a false positive. Identical technique to OCR's own
    `image_analysis.detect_orientation()`, self-contained here.
    """

    import numpy as np

    grayscale = image.convert("L")
    grayscale.thumbnail((400, 400))

    scores: dict[int, float] = {}

    for degrees in _ORIENTATION_CANDIDATES:
        rotated = grayscale.rotate(degrees, expand=True) if degrees else grayscale
        array = np.asarray(rotated, dtype=np.float64)
        scores[degrees] = float(array.mean(axis=1).var())

    ordered = sorted(scores.items(), key=lambda item: -item[1])
    best_degrees, best_score = ordered[0]
    total = sum(score for _, score in ordered) or 1.0
    margin = (best_score - ordered[1][1]) / total if len(ordered) > 1 else 1.0

    return RotationResult(
        degrees=best_degrees, confidence=round(max(0.0, min(1.0, margin)), 4)
    )


def _laplacian_variance(array: "np.ndarray") -> float:
    """Classical "variance of Laplacian" sharpness metric via a plain
    3x3 discrete Laplacian convolution -- no `scipy`/`opencv` needed."""

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
    """Sharpness measurement -- see `detect_blur()`."""

    variance: float
    is_blurry: bool


def detect_blur(
    image: "Image", *, threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD
) -> BlurResult:
    """
    Classical "variance of Laplacian" blur metric (the exact technique
    the task's own "Blur detection -> OpenCV variance of Laplacian"
    guidance names, reimplemented here in plain numpy rather than
    adding an `opencv` dependency purely for this one metric -- OCR's
    own `image_analysis.detect_blur()` makes the identical judgment).
    A sharp image has strong, varied edges (high-variance Laplacian
    response); a blurry one's edges are smoothed out. `threshold` is
    an empirical cutoff, tunable via `[vision].blur_variance_threshold`.
    """

    import numpy as np

    array = np.asarray(image.convert("L"), dtype=np.float64)
    variance = _laplacian_variance(array)

    return BlurResult(variance=round(variance, 2), is_blurry=variance < threshold)


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityResult:
    """Composite deterministic image quality assessment -- see `compute_quality_score()`."""

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
) -> QualityResult:
    """
    Composite, deterministic image quality score in `[0, 1]`,
    combining resolution, sharpness (blur variance), and contrast/
    brightness -- an inexpensive triage signal computed without any
    model call. `vision.analyze_image_quality`'s primary result.
    """

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
        0.35 * resolution_component
        + 0.35 * sharpness_component
        + 0.15 * contrast_component
        + 0.15 * brightness_component
    )

    warnings: list[str] = []

    if is_low_resolution:
        warnings.append("Image resolution is low.")
    if blur.is_blurry:
        warnings.append("Image appears blurry.")
    if contrast_component < 0.3:
        warnings.append("Image has low contrast.")

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


@dataclass(frozen=True, slots=True, kw_only=True)
class AnomalyResult:
    """Statistical outlier-region assessment -- see `detect_anomalous_regions()`."""

    regions: tuple[regions.BoundingBox, ...]
    anomaly_score: float
    has_anomalies: bool


def detect_anomalous_regions(
    image: "Image",
    *,
    grid: int = DEFAULT_ANOMALY_GRID,
    z_threshold: float = DEFAULT_ANOMALY_Z_THRESHOLD,
) -> AnomalyResult:
    """
    Deterministic statistical-outlier scan: partition `image` into a
    `grid` x `grid` array of blocks, compute each block's mean
    brightness, and flag blocks whose brightness deviates from the
    image's own block-mean distribution by at least `z_threshold`
    standard deviations (a classical z-score outlier test -- never a
    trained anomaly-detection model). This is a genuinely useful,
    honest, *statistical* anomaly signal (unusually bright/dark
    regions relative to the rest of the image) -- not semantic
    anomaly understanding (e.g. "a person where there shouldn't be
    one"), which `vision.detect_anomalies`'s ToolDriver only obtains
    by falling back to its Provider-backed Capability when the caller
    asks for that kind of interpretation.
    """

    import numpy as np

    grayscale = image.convert("L")
    width, height = grayscale.size
    block_width = max(1, width // grid)
    block_height = max(1, height // grid)

    array = np.asarray(grayscale, dtype=np.float64)
    block_means: list[float] = []
    block_boxes: list[tuple[int, int, int, int]] = []

    for row in range(grid):
        for col in range(grid):
            x0, y0 = col * block_width, row * block_height
            x1 = width if col == grid - 1 else x0 + block_width
            y1 = height if row == grid - 1 else y0 + block_height

            block = array[y0:y1, x0:x1]
            if block.size == 0:
                continue

            block_means.append(float(block.mean()))
            block_boxes.append((x0, y0, x1 - x0, y1 - y0))

    means_array = np.asarray(block_means)
    overall_mean = float(means_array.mean()) if means_array.size else 0.0
    overall_std = float(means_array.std()) if means_array.size else 0.0

    anomalous: list[regions.BoundingBox] = []
    max_z = 0.0

    if overall_std > 0:
        for mean, (x, y, w, h) in zip(block_means, block_boxes):
            z_score = abs(mean - overall_mean) / overall_std
            max_z = max(max_z, z_score)

            if z_score >= z_threshold:
                anomalous.append(
                    regions.BoundingBox(x=x, y=y, width=w, height=h, area=w * h)
                )

    anomalous.sort(key=lambda box: -box.area)

    return AnomalyResult(
        regions=tuple(anomalous),
        anomaly_score=round(min(1.0, max_z / (z_threshold * 2)) if z_threshold else 0.0, 4),
        has_anomalies=bool(anomalous),
    )
