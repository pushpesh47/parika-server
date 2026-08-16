"""
PARIKA Video Module - Deterministic Thumbnail/Contact-Sheet Generation

Pure Pillow image compositing -- no model call. Backs
`video.extract_thumbnails`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


def build_contact_sheet(
    images: list["Image"],
    *,
    columns: int,
    cell_width: int,
) -> "Image":
    """
    Compose `images` (already decoded, in order) into a single grid
    contact sheet, each cell resized to `cell_width` wide preserving
    its own aspect ratio. Rows are computed from `len(images)` and
    `columns`; the sheet's own dimensions are exactly
    `columns * cell_width` wide.
    """

    from PIL import Image as PILImage

    if not images:
        raise ValueError("build_contact_sheet() requires at least one image.")

    columns = max(1, columns)
    rows = (len(images) + columns - 1) // columns

    resized: list[Image] = []
    max_cell_height = 0

    for image in images:
        width, height = image.size
        scale = cell_width / width if width else 1.0
        cell_height = max(1, round(height * scale))
        resized_image = image.convert("RGB").resize(
            (cell_width, cell_height), PILImage.Resampling.LANCZOS
        )
        resized.append(resized_image)
        max_cell_height = max(max_cell_height, cell_height)

    sheet = PILImage.new(
        "RGB", (columns * cell_width, rows * max_cell_height), color=(20, 20, 20)
    )

    for position, resized_image in enumerate(resized):
        column = position % columns
        row = position // columns
        sheet.paste(resized_image, (column * cell_width, row * max_cell_height))

    return sheet
