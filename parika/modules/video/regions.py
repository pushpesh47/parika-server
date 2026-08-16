"""
PARIKA Video Module - Deterministic Connected-Component Region Labeling

Pure numpy connected-component labeling (4-connectivity, iterative
stack-based flood fill), self-contained within this Module exactly
like every other Module in this codebase keeps its own deterministic
algorithms self-contained (Modules reuse one another only through a
Capability, via a `Goal`, never a direct Python import of internals --
see `parika/modules/vision/quality.py`'s own docstring for the
precedent). Identical technique to `parika/modules/vision/regions.py`.

Shared by `motion.py` (motion regions) and `quality.py`/other
deterministic algorithms in this Module that need bounding boxes over
a binary mask.
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

    def to_result_dict(self) -> dict[str, object]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def label_regions(
    mask: "np.ndarray", *, min_area: int = 25, max_regions: int = 50
) -> tuple[BoundingBox, ...]:
    """
    Label every 4-connected `True` region in the 2D boolean `mask`,
    returning up to `max_regions` bounding boxes with at least
    `min_area` pixels, sorted by area descending.
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
