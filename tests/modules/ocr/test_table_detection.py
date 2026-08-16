"""
Unit tests for the OCR Module's deterministic table-region detection
(`parika.modules.ocr.table_detection`). Uses real Pillow/numpy against
small synthetic images - never a Provider, never Brain/Goal.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from parika.modules.ocr import table_detection


def _grid_image(width: int = 400, height: int = 300) -> Image.Image:
    """A synthetic ruled table: 5 horizontal and 5 vertical lines."""

    image = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)

    for y in range(20, height, 60):
        draw.line([(20, y), (width - 20, y)], fill=0, width=2)

    for x in range(20, width, 90):
        draw.line([(x, 20), (x, height - 40)], fill=0, width=2)

    return image.convert("RGB")


class TestTableRegionDetection:
    def test_detects_ruled_grid(self) -> None:
        grid = _grid_image()

        regions = table_detection.detect_table_regions(grid)

        assert len(regions) == 1
        assert len(regions[0].row_lines) == 5
        assert len(regions[0].column_lines) == 5

    def test_blank_image_has_no_table(self) -> None:
        blank = Image.new("RGB", (400, 300), color=255)

        assert table_detection.detect_table_regions(blank) == ()

    def test_too_few_lines_is_not_a_table(self) -> None:
        image = Image.new("L", (400, 300), color=255)
        draw = ImageDraw.Draw(image)
        draw.line([(20, 50), (380, 50)], fill=0, width=2)
        image_rgb = image.convert("RGB")

        assert table_detection.detect_table_regions(image_rgb) == ()

    def test_returned_region_reports_pixel_bounds(self) -> None:
        grid = _grid_image()

        region = table_detection.detect_table_regions(grid)[0]

        assert region.x == region.column_lines[0]
        assert region.y == region.row_lines[0]
        assert region.width == region.column_lines[-1] - region.column_lines[0]
        assert region.height == region.row_lines[-1] - region.row_lines[0]
