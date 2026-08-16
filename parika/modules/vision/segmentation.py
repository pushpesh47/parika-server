"""
PARIKA Vision Module - Deterministic Background Removal

`remove_background()` -- OpenCV's classical GrabCut algorithm
(`cv2.grabCut`), a graph-cut energy-minimization technique from 2004,
*not* a trained neural segmentation model -- run with an automatic
rectangular seed (the image with a small margin trimmed off, on the
common assumption the subject is roughly centered and the border is
background). This is the deterministic, non-learned segmentation
path `vision.remove_background` always tries first, matching this
Module's "prefer deterministic computer vision algorithms before
invoking a Vision Language Model" mandate; no bundled neural
foreground-segmentation model (e.g. U2-Net) exists anywhere in this
codebase, and downloading one purely for this one Capability would be
a heavier, less honest dependency than reusing the classical
algorithm OpenCV already ships.

Requires the optional `vision` dependency group
(`opencv-python-headless`); raises `VisionDependencyUnavailableError`
up front when unavailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import require_opencv

if TYPE_CHECKING:
    from PIL.Image import Image

DEFAULT_MARGIN_RATIO = 0.05
DEFAULT_ITERATIONS = 5


def remove_background(
    image: "Image",
    *,
    margin_ratio: float = DEFAULT_MARGIN_RATIO,
    iterations: int = DEFAULT_ITERATIONS,
) -> "Image":
    """
    Segment `image`'s foreground via `cv2.grabCut()`, seeded with a
    rectangle inset by `margin_ratio` on every side, and return an
    RGBA copy with the background made fully transparent. A purely
    classical (non-learned) computer vision algorithm; never a model
    call.
    """

    require_opencv()

    import cv2
    import numpy as np
    from PIL import Image as PILImage

    rgb_array = np.asarray(image.convert("RGB"))
    height, width = rgb_array.shape[:2]

    margin_x = max(1, int(width * margin_ratio))
    margin_y = max(1, int(height * margin_ratio))
    rect = (
        margin_x,
        margin_y,
        max(1, width - 2 * margin_x),
        max(1, height - 2 * margin_y),
    )

    mask = np.zeros((height, width), dtype=np.uint8)
    background_model = np.zeros((1, 65), dtype=np.float64)
    foreground_model = np.zeros((1, 65), dtype=np.float64)

    bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

    cv2.grabCut(
        bgr_array,
        mask,
        rect,
        background_model,
        foreground_model,
        iterations,
        cv2.GC_INIT_WITH_RECT,
    )

    foreground_mask = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype("uint8")

    rgba = image.convert("RGBA")
    alpha = PILImage.fromarray(foreground_mask, mode="L")
    rgba.putalpha(alpha)
    return rgba
