"""
PARIKA Video Module - Deterministic Per-Frame Quality Analysis

Pure Pillow/numpy frame metrics -- no model call, self-contained
within this Module (see `regions.py`'s docstring). Backs
`video.detect_blur`, `video.detect_black_frames`,
`video.detect_rotation`, and `video.detect_corruption`: every one of
these Capabilities is 100% deterministic by design (the task's own
"Do not use an LLM for these capabilities" instruction) -- there is
no Provider-backed escalation path for any of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

_ORIENTATION_CANDIDATES = (0, 90, 180, 270)
_LAPLACIAN_KERNEL_CENTER = -4.0

DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0
DEFAULT_BLACK_FRAME_BRIGHTNESS_THRESHOLD = 16.0


def _laplacian_variance(array) -> float:
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
    variance: float
    is_blurry: bool


def detect_blur(
    image: "Image", *, threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD
) -> BlurResult:
    """
    Classical "variance of Laplacian" sharpness metric -- identical
    technique to `vision/quality.py`'s own `detect_blur()`,
    reimplemented here in plain numpy rather than importing it (see
    `regions.py`'s docstring).
    """

    import numpy as np

    array = np.asarray(image.convert("L"), dtype=np.float64)
    variance = _laplacian_variance(array)

    return BlurResult(variance=round(variance, 2), is_blurry=variance < threshold)


@dataclass(frozen=True, slots=True, kw_only=True)
class BlackFrameResult:
    mean_brightness: float
    is_black: bool


def detect_black_frame(
    image: "Image", *, threshold: float = DEFAULT_BLACK_FRAME_BRIGHTNESS_THRESHOLD
) -> BlackFrameResult:
    """
    A frame is "black" when its mean grayscale brightness (0-255)
    falls below `threshold` -- catches fade-to-black transitions,
    dropped/blank frames, and leading/trailing black padding.
    """

    import numpy as np

    array = np.asarray(image.convert("L"), dtype=np.float64)
    mean_brightness = float(array.mean())

    return BlackFrameResult(
        mean_brightness=round(mean_brightness, 2),
        is_black=mean_brightness < threshold,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class RotationResult:
    degrees: int
    confidence: float


def detect_rotation(image: "Image") -> RotationResult:
    """
    Best-effort deterministic gross-rotation guess via the row-
    projection-profile heuristic -- identical technique to
    `vision/quality.py`'s own `detect_rotation()`/OCR's
    `image_analysis.detect_orientation()`, reimplemented here
    self-contained.
    """

    import numpy as np

    grayscale = image.convert("L")
    grayscale.thumbnail((300, 300))

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
