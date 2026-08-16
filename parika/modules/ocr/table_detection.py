"""
PARIKA OCR Module - Deterministic Table-Region Detection

Split out of `preprocessing.py` purely to keep that file within the
project's File Size Guidelines (`docs/architecture/
PARIKA_Core_Coding_Standards.md`) - table-region detection is already
a cohesive, independently testable algorithm (Otsu thresholding plus
row/column projection profiles), used only by
`structured_driver.OcrTableToolDriver`.

Requires the optional `Pillow`/`numpy` dependency pair, exactly like
the rest of `preprocessing.py`; raises `OcrDependencyUnavailableError`
when unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import require_imaging

if TYPE_CHECKING:
    import numpy as np
    from PIL.Image import Image


def _otsu_threshold(array: "np.ndarray") -> float:
    """
    Classical Otsu global thresholding: picks the grayscale cutoff
    that maximizes between-class (ink vs. background) variance, from
    the image's own histogram - no external dependency beyond numpy.
    """

    import numpy as np

    histogram, _ = np.histogram(array, bins=256, range=(0, 256))
    histogram = histogram.astype(np.float64)
    total = histogram.sum()

    if total <= 0:
        return 128.0

    intensities = np.arange(256, dtype=np.float64)
    sum_all = float(np.dot(histogram, intensities))

    weight_background = 0.0
    sum_background = 0.0
    best_threshold = 0
    best_between_variance = -1.0

    for level in range(256):
        weight_background += histogram[level]

        if weight_background <= 0.0:
            continue

        weight_foreground = total - weight_background

        if weight_foreground <= 0.0:
            break

        sum_background += level * histogram[level]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground

        between_variance = (
            weight_background
            * weight_foreground
            * (mean_background - mean_foreground) ** 2
        )

        # `>=`, not `>`: a near-binary image (a few pure-ink pixels
        # against a large, uniform paper background - exactly a
        # ruled-line table on a clean scan) produces a *tied* maximum
        # between-class variance across the whole empty range between
        # the two extremes. Preferring the *last* tied level keeps the
        # chosen threshold on the bright side of that range, so
        # `array < threshold` actually separates the dark ink pixels
        # from the bright background instead of degenerating to 0.
        if between_variance >= best_between_variance:
            best_between_variance = between_variance
            best_threshold = level

    return float(best_threshold)


def _cluster_positions(
    positions: tuple[int, ...], *, max_gap: int = 3
) -> tuple[int, ...]:
    """Merge adjacent/close pixel indices (a thick line spans several rows/columns) into one."""

    if not positions:
        return ()

    clusters: list[list[int]] = [[positions[0]]]

    for position in positions[1:]:
        if position - clusters[-1][-1] <= max_gap:
            clusters[-1].append(position)
        else:
            clusters.append([position])

    return tuple(round(sum(cluster) / len(cluster)) for cluster in clusters)


@dataclass(frozen=True, slots=True, kw_only=True)
class TableRegion:
    """One detected probable table region - see `detect_table_regions()`."""

    x: int
    y: int
    width: int
    height: int
    row_lines: tuple[int, ...]
    column_lines: tuple[int, ...]


def detect_table_regions(
    image: "Image",
    *,
    min_row_lines: int = 3,
    min_column_lines: int = 2,
    line_coverage_ratio: float = 0.5,
) -> tuple[TableRegion, ...]:
    """
    Lightweight, deterministic table-region detector, never an LLM
    call: binarizes the image (Otsu thresholding), then finds long,
    mostly-continuous horizontal and vertical dark runs (candidate
    ruling lines) via row/column projection profiles. A region
    enclosed by at least `min_row_lines` row-lines and
    `min_column_lines` column-lines is reported as a probable table,
    with the detected line positions as its coordinates.

    Reliably detects ruled/gridded tables (the common case for
    invoices, forms, and bank statements). Borderless tables (no
    visible ruling lines) are *not* detected by this heuristic - a
    dedicated computer-vision library (e.g. OpenCV's contour/Hough-
    line detection) would be needed for that case; see
    `preprocessing.py`'s top-level docstring and the OCR Module's
    recommended extensions.
    """

    require_imaging()

    import numpy as np

    array = np.asarray(image.convert("L"), dtype=np.float64)
    threshold = _otsu_threshold(array)
    dark_pixels = array < threshold

    height, width = dark_pixels.shape

    if height == 0 or width == 0:
        return ()

    row_coverage = dark_pixels.sum(axis=1) / width
    column_coverage = dark_pixels.sum(axis=0) / height

    row_lines = _cluster_positions(
        tuple(
            int(i) for i, coverage in enumerate(row_coverage) if coverage >= line_coverage_ratio
        )
    )
    column_lines = _cluster_positions(
        tuple(
            int(i)
            for i, coverage in enumerate(column_coverage)
            if coverage >= line_coverage_ratio
        )
    )

    if len(row_lines) < min_row_lines or len(column_lines) < min_column_lines:
        return ()

    region = TableRegion(
        x=column_lines[0],
        y=row_lines[0],
        width=column_lines[-1] - column_lines[0],
        height=row_lines[-1] - row_lines[0],
        row_lines=row_lines,
        column_lines=column_lines,
    )
    return (region,)
