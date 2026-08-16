"""
PARIKA Vision Module - Deterministic Perceptual Hashing & Image Comparison

Pure Pillow/numpy image-similarity primitives -- no model call, no
filesystem access, no Brain/Goal/Capability concept -- mirroring
`ocr/image_analysis.py`'s own shape exactly: a clean, independently
testable algorithmic layer the new ToolDrivers in this Module call,
never the other way around.

Backs `vision.compare_images`, `vision.detect_differences`,
`vision.find_similar_images`, and `vision.find_duplicates`: every one
of them is, at its core, "how similar/different are these two (or
more) images" -- the exact "prefer deterministic pixel/perceptual
similarity before invoking a Vision Language Model" requirement,
taken literally. A Vision Language Model is only ever consulted by
the ToolDrivers built on top of this module when the caller
explicitly wants a semantic narrative of *why* two images differ, not
merely a similarity score.

Two complementary perceptual hashes are used together (never just
one), since each is blind to a different kind of change:

- `average_hash()` (aHash): each bit is "is this cell brighter than
  the image's own average brightness" -- robust to the exact pixel
  values, but blind to any change (e.g. inverted contrast) that
  preserves the overall brightness ordering.
- `difference_hash()` (dHash): each bit is "is this cell brighter
  than its right neighbor" -- a gradient signature, robust to small
  brightness/contrast shifts but blind to a uniform region's exact
  darkness.

Neither is cryptographic or exact; both are the same well-established,
widely used technique the `imagehash` PyPI package implements (not a
dependency here -- reimplemented in ~15 lines of numpy each, exactly
the same "no unnecessary dependency" judgment OCR's own
`image_analysis.py` already makes for its Laplacian-variance blur
metric).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import regions

if TYPE_CHECKING:
    from PIL.Image import Image

DEFAULT_HASH_SIZE = 8
DEFAULT_DIFF_THRESHOLD = 30
DEFAULT_DIFF_MIN_AREA = 25
DEFAULT_MAX_DIFF_REGIONS = 20
_COMMON_COMPARISON_SIZE = (256, 256)
_HISTOGRAM_BINS = 64


def _grayscale_array(image: "Image", size: tuple[int, int] | None = None):
    import numpy as np

    grayscale = image.convert("L")

    if size is not None:
        from PIL import Image as PILImage

        grayscale = grayscale.resize(size, PILImage.Resampling.LANCZOS)

    return np.asarray(grayscale, dtype=np.float64)


def average_hash(image: "Image", *, hash_size: int = DEFAULT_HASH_SIZE) -> int:
    """
    Classical "average hash": resize to `hash_size` x `hash_size`,
    then set bit `(row * hash_size + col)` whenever that cell is
    brighter than the resized image's own mean brightness.
    """

    array = _grayscale_array(image, (hash_size, hash_size))
    mean = array.mean()

    value = 0
    for bit, pixel in enumerate(array.flatten()):
        if pixel > mean:
            value |= 1 << bit

    return value


def difference_hash(image: "Image", *, hash_size: int = DEFAULT_HASH_SIZE) -> int:
    """
    Classical "difference hash": resize to `(hash_size + 1) x
    hash_size`, then set bit `(row * hash_size + col)` whenever cell
    `(row, col)` is brighter than its immediate right neighbor
    `(row, col + 1)` -- a horizontal-gradient signature.
    """

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
    """Number of differing bits between two equal-width hash integers."""

    return bin(a ^ b).count("1")


def hash_similarity(distance: int, *, hash_size: int = DEFAULT_HASH_SIZE) -> float:
    """Normalize a Hamming distance over `hash_size ** 2` bits into `[0, 1]`."""

    bits = hash_size * hash_size
    return round(max(0.0, 1.0 - (distance / bits)), 4) if bits else 0.0


def histogram_similarity(image_a: "Image", image_b: "Image") -> float:
    """
    Grayscale-histogram intersection in `[0, 1]`: the fraction of
    normalized tonal distribution the two images share, regardless of
    spatial layout -- catches global recolor/exposure differences
    that a perceptual hash (spatially structured) can miss.
    """

    import numpy as np

    array_a = _grayscale_array(image_a)
    array_b = _grayscale_array(image_b)

    hist_a, _ = np.histogram(array_a, bins=_HISTOGRAM_BINS, range=(0, 255))
    hist_b, _ = np.histogram(array_b, bins=_HISTOGRAM_BINS, range=(0, 255))

    hist_a = hist_a / max(1, hist_a.sum())
    hist_b = hist_b / max(1, hist_b.sum())

    return round(float(np.minimum(hist_a, hist_b).sum()), 4)


def pixel_similarity(image_a: "Image", image_b: "Image") -> float:
    """
    Normalized-RMSE pixel similarity in `[0, 1]`, computed over both
    images resized to one common `_COMMON_COMPARISON_SIZE` so
    differently-sized inputs remain comparable -- catches exact
    spatial pixel differences a histogram cannot (two images can
    share an identical histogram while looking nothing alike).
    """

    import numpy as np

    array_a = _grayscale_array(image_a, _COMMON_COMPARISON_SIZE)
    array_b = _grayscale_array(image_b, _COMMON_COMPARISON_SIZE)

    rmse = float(np.sqrt(np.mean((array_a - array_b) ** 2)))
    return round(max(0.0, 1.0 - (rmse / 255.0)), 4)


@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonResult:
    """Composite deterministic similarity assessment -- see `compare_images()`."""

    perceptual_hash_distance: int
    perceptual_hash_similarity: float
    pixel_similarity: float
    histogram_similarity: float
    overall_similarity: float
    same_dimensions: bool


def compare_images(
    image_a: "Image", image_b: "Image", *, hash_size: int = DEFAULT_HASH_SIZE
) -> ComparisonResult:
    """
    Composite, deterministic image similarity in `[0, 1]`, combining
    difference-hash Hamming distance, pixel-level RMSE, and grayscale
    histogram intersection -- never a model call. This is the
    "pixel/perceptual similarity before VLM" step `vision.compare_images`
    always runs; a Vision Language Model is only consulted afterwards,
    and only when the caller explicitly asks for a semantic
    explanation of *why* the images differ.
    """

    distance = hamming_distance(
        difference_hash(image_a, hash_size=hash_size),
        difference_hash(image_b, hash_size=hash_size),
    )
    hash_sim = hash_similarity(distance, hash_size=hash_size)
    pixel_sim = pixel_similarity(image_a, image_b)
    hist_sim = histogram_similarity(image_a, image_b)

    overall = round((hash_sim * 0.4) + (pixel_sim * 0.4) + (hist_sim * 0.2), 4)

    return ComparisonResult(
        perceptual_hash_distance=distance,
        perceptual_hash_similarity=hash_sim,
        pixel_similarity=pixel_sim,
        histogram_similarity=hist_sim,
        overall_similarity=overall,
        same_dimensions=image_a.size == image_b.size,
    )


def find_diff_regions(
    image_a: "Image",
    image_b: "Image",
    *,
    threshold: int = DEFAULT_DIFF_THRESHOLD,
    min_area: int = DEFAULT_DIFF_MIN_AREA,
    max_regions: int = DEFAULT_MAX_DIFF_REGIONS,
) -> tuple[regions.BoundingBox, ...]:
    """
    Locate the axis-aligned bounding boxes of every visually-differing
    region between `image_a` and `image_b`, via absolute grayscale
    pixel difference thresholded at `threshold` then labeled by
    `regions.label_regions()` -- a purely deterministic, classical
    technique, never a model call. Both images are resized to a
    shared thumbnail size first, both for comparability (their native
    resolutions may differ) and for `label_regions()`'s own
    performance expectations.
    """

    import numpy as np

    array_a = _grayscale_array(image_a, _COMMON_COMPARISON_SIZE)
    array_b = _grayscale_array(image_b, _COMMON_COMPARISON_SIZE)

    mask = np.abs(array_a - array_b) >= threshold
    return regions.label_regions(mask, min_area=min_area, max_regions=max_regions)


def difference_ratio(
    image_a: "Image", image_b: "Image", *, threshold: int = DEFAULT_DIFF_THRESHOLD
) -> float:
    """Fraction, in `[0, 1]`, of pixels that differ by at least `threshold`."""

    import numpy as np

    array_a = _grayscale_array(image_a, _COMMON_COMPARISON_SIZE)
    array_b = _grayscale_array(image_b, _COMMON_COMPARISON_SIZE)

    mask = np.abs(array_a - array_b) >= threshold
    return round(float(mask.mean()), 4)
