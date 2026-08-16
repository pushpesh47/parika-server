"""
PARIKA Video Module - Deterministic Frame Perceptual Hashing

Pure Pillow/numpy frame-similarity primitives, self-contained within
this Module (see `regions.py`'s own docstring for why -- Modules
never import one another's deterministic-algorithm internals).
Identical difference-hash technique to
`parika/modules/vision/hashing.py`, applied to decoded video frames
rather than files read from disk.

Backs `scene_detection.py` (shot-boundary detection), `video.
extract_text`'s repeated-text-frame dedup, and `video.compare_frames`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import regions

if TYPE_CHECKING:
    from PIL.Image import Image

DEFAULT_HASH_SIZE = 8
_COMMON_COMPARISON_SIZE = (160, 160)
_HISTOGRAM_BINS = 32
DEFAULT_DIFF_THRESHOLD = 30
DEFAULT_DIFF_MIN_AREA = 16


def _grayscale_array(image: "Image", size: tuple[int, int] | None = None):
    import numpy as np

    grayscale = image.convert("L")

    if size is not None:
        from PIL import Image as PILImage

        grayscale = grayscale.resize(size, PILImage.Resampling.LANCZOS)

    return np.asarray(grayscale, dtype=np.float64)


def difference_hash(image: "Image", *, hash_size: int = DEFAULT_HASH_SIZE) -> int:
    """Classical "difference hash" -- see `vision/hashing.py`'s identical technique."""

    array = _grayscale_array(image, (hash_size + 1, hash_size))

    value = 0
    bit = 0
    for row in range(hash_size):
        for col in range(hash_size):
            if array[row, col] > array[row, col + 1]:
                value |= 1 << bit
            bit += 1

    return value


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def hash_distance_ratio(a: int, b: int, *, hash_size: int = DEFAULT_HASH_SIZE) -> float:
    """Hamming distance normalized to `[0, 1]` over `hash_size ** 2` bits."""

    bits = hash_size * hash_size
    return round(hamming_distance(a, b) / bits, 4) if bits else 0.0


def histogram_delta(image_a: "Image", image_b: "Image") -> float:
    """
    Grayscale-histogram delta in `[0, 1]` (`1 - intersection`) --
    catches global brightness/exposure shifts a spatial hash can
    miss, complementing `difference_hash()` exactly like
    `vision/hashing.py`'s own histogram/hash blend.
    """

    import numpy as np

    array_a = _grayscale_array(image_a)
    array_b = _grayscale_array(image_b)

    hist_a, _ = np.histogram(array_a, bins=_HISTOGRAM_BINS, range=(0, 255))
    hist_b, _ = np.histogram(array_b, bins=_HISTOGRAM_BINS, range=(0, 255))

    hist_a = hist_a / max(1, hist_a.sum())
    hist_b = hist_b / max(1, hist_b.sum())

    intersection = float(np.minimum(hist_a, hist_b).sum())
    return round(1.0 - intersection, 4)


def pixel_similarity(image_a: "Image", image_b: "Image") -> float:
    """Normalized-RMSE pixel similarity in `[0, 1]` over a shared thumbnail size."""

    import numpy as np

    array_a = _grayscale_array(image_a, _COMMON_COMPARISON_SIZE)
    array_b = _grayscale_array(image_b, _COMMON_COMPARISON_SIZE)

    rmse = float(np.sqrt(np.mean((array_a - array_b) ** 2)))
    return round(max(0.0, 1.0 - (rmse / 255.0)), 4)


@dataclass(frozen=True, slots=True, kw_only=True)
class FrameChangeScore:
    """Composite frame-to-frame change score -- see `change_score()`."""

    hash_distance_ratio: float
    histogram_delta: float
    pixel_dissimilarity: float
    overall: float


def change_score(image_a: "Image", image_b: "Image") -> FrameChangeScore:
    """
    Composite, deterministic frame-to-frame change score in `[0, 1]`
    (0 = identical, 1 = maximally different), blending difference-
    hash distance, histogram delta, and pixel dissimilarity -- the
    metric `scene_detection.py`'s shot-boundary detector thresholds
    against. Never a model call.
    """

    hash_a = difference_hash(image_a)
    hash_b = difference_hash(image_b)
    hash_ratio = hash_distance_ratio(hash_a, hash_b)
    hist_delta = histogram_delta(image_a, image_b)
    pixel_dissim = 1.0 - pixel_similarity(image_a, image_b)

    overall = round((hash_ratio * 0.5) + (hist_delta * 0.2) + (pixel_dissim * 0.3), 4)

    return FrameChangeScore(
        hash_distance_ratio=hash_ratio,
        histogram_delta=hist_delta,
        pixel_dissimilarity=pixel_dissim,
        overall=overall,
    )


def find_diff_regions(
    image_a: "Image",
    image_b: "Image",
    *,
    threshold: int = DEFAULT_DIFF_THRESHOLD,
    min_area: int = DEFAULT_DIFF_MIN_AREA,
    max_regions: int = 20,
) -> tuple[regions.BoundingBox, ...]:
    """Axis-aligned bounding boxes of visually-differing regions -- backs `video.compare_frames`."""

    import numpy as np

    array_a = _grayscale_array(image_a, _COMMON_COMPARISON_SIZE)
    array_b = _grayscale_array(image_b, _COMMON_COMPARISON_SIZE)

    mask = np.abs(array_a - array_b) >= threshold
    return regions.label_regions(mask, min_area=min_area, max_regions=max_regions)
