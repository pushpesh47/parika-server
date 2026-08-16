"""
PARIKA Vision Module - Deterministic Connected-Component Region Labeling

Pure numpy connected-component labeling (4-connectivity, iterative
stack-based flood fill -- no `scipy`/`opencv` dependency required),
shared by every deterministic Capability in this Module that needs
bounding boxes over a binary mask: `hashing.find_diff_regions()`
(`vision.detect_differences`), `detectors.count_blobs()`
(`vision.count_objects`'s deterministic fast path), and
`quality.detect_anomalous_regions()` (`vision.detect_anomalies`).
Mirrors OCR's own precedent of avoiding a `scipy`/`opencv` dependency
for a lightweight classical technique
(`parika/modules/ocr/image_analysis.py`'s own Laplacian convolution).

Callers are expected to downscale (e.g. via `Image.thumbnail()`)
before building a mask -- exactly like OCR's own orientation/skew
detection downscales to 400x400/600x600 first -- since this is a
plain Python flood fill, not a vectorized algorithm; it is fast
enough for the thumbnail-sized masks every caller in this Module
passes it, not for full-resolution photographs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True, slots=True, kw_only=True)
class BoundingBox:
    """One labeled region's axis-aligned pixel bounding box."""

    x: int
    y: int
    width: int
    height: int
    area: int


def label_regions(
    mask: "np.ndarray", *, min_area: int = 25, max_regions: int = 50
) -> tuple[BoundingBox, ...]:
    """
    Label every 4-connected `True` region in the 2D boolean `mask`,
    returning up to `max_regions` bounding boxes with at least
    `min_area` pixels, sorted by area descending (largest, typically
    most significant, regions first).
    """

    import numpy as np

    visited = np.zeros_like(mask, dtype=bool)
    height, width = mask.shape
    boxes: list[BoundingBox] = []

    for start_y in range(height):
        for start_x in range(width):
            if not mask[start_y, start_x] or visited[start_y, start_x]:
                continue

            stack = [(start_y, start_x)]
            visited[start_y, start_x] = True
            min_x = max_x = start_x
            min_y = max_y = start_y
            area = 0

            while stack:
                y, x = stack.pop()
                area += 1
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)

                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if (
                        0 <= ny < height
                        and 0 <= nx < width
                        and mask[ny, nx]
                        and not visited[ny, nx]
                    ):
                        visited[ny, nx] = True
                        stack.append((ny, nx))

            if area >= min_area:
                boxes.append(
                    BoundingBox(
                        x=min_x,
                        y=min_y,
                        width=max_x - min_x + 1,
                        height=max_y - min_y + 1,
                        area=area,
                    )
                )

    boxes.sort(key=lambda box: -box.area)
    return tuple(boxes[:max_regions])
