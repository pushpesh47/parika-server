"""
PARIKA Video Module - Deterministic Motion Analysis

Pure numpy frame-differencing -- no model call, self-contained
within this Module. Backs `video.detect_motion` and contributes the
deterministic "object appears/disappears"-adjacent signal
`driver_events.py`'s `video.detect_events` also uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import regions

if TYPE_CHECKING:
    from PIL.Image import Image

DEFAULT_PIXEL_THRESHOLD = 25
DEFAULT_MIN_REGION_AREA = 40
_COMPARISON_SIZE = (160, 160)


@dataclass(frozen=True, slots=True, kw_only=True)
class MotionResult:
    """Deterministic motion assessment between two consecutive frames."""

    changed_pixel_ratio: float
    has_motion: bool
    regions: tuple[regions.BoundingBox, ...]


def detect_motion(
    previous_image: "Image",
    current_image: "Image",
    *,
    pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD,
    area_ratio_threshold: float = 0.01,
    min_region_area: int = DEFAULT_MIN_REGION_AREA,
) -> MotionResult:
    """
    Absolute grayscale frame-differencing thresholded at
    `pixel_threshold`, connected-component labeled into candidate
    motion regions. `has_motion` fires when the changed-pixel ratio
    meets `area_ratio_threshold` -- a classical, deterministic
    technique (never optical flow/a model), matching the task's own
    "prefer deterministic computer-vision techniques" instruction.
    """

    import numpy as np
    from PIL import Image as PILImage

    array_a = np.asarray(
        previous_image.convert("L").resize(_COMPARISON_SIZE, PILImage.Resampling.LANCZOS),
        dtype=np.float64,
    )
    array_b = np.asarray(
        current_image.convert("L").resize(_COMPARISON_SIZE, PILImage.Resampling.LANCZOS),
        dtype=np.float64,
    )

    mask = np.abs(array_a - array_b) >= pixel_threshold
    changed_ratio = round(float(mask.mean()), 4)
    boxes = regions.label_regions(mask, min_area=min_region_area, max_regions=25)

    return MotionResult(
        changed_pixel_ratio=changed_ratio,
        has_motion=changed_ratio >= area_ratio_threshold,
        regions=boxes,
    )
