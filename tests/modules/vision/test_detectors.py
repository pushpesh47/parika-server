"""
Unit tests for the Vision Module's deterministic face/QR/barcode
detectors and heuristic classifier/blob-counter
(`parika.modules.vision.detectors`).

QR/barcode tests generate real, decodable fixture images at test time
via the `qrcode`/`python-barcode` packages (test-only dependencies,
`pyproject.toml`'s `dev` extra) and decode them with the real ZBar
backend (`pyzbar`) -- never a binary fixture file, matching this
project's established "always generate test images programmatically"
convention (`tests/modules/ocr/test_image_analysis.py`).

Face detection is exercised against its real classical algorithm for
its honest negative case (no face in a blank image) and its
`VisionDependencyUnavailableError` guard; the actual Haar-cascade
detection quality against a real photograph was manually verified
during development (a synthetic PIL drawing cannot reliably trigger a
trained cascade, and this project does not commit binary image
fixtures), and its cascade-to-`FaceRegion` mapping is covered via a
monkeypatched cascade.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from parika.modules.vision import config, detectors
from parika.modules.vision.exceptions import VisionDependencyUnavailableError

pyzbar = pytest.importorskip("pyzbar.pyzbar")
qrcode = pytest.importorskip("qrcode")
barcode = pytest.importorskip("barcode")
cv2 = pytest.importorskip("cv2")


class TestDetectFaces:
    def test_returns_empty_tuple_for_a_blank_image(self) -> None:
        blank = Image.new("RGB", (200, 200), color=(200, 200, 200))

        assert detectors.detect_faces(blank) == ()

    def test_raises_when_opencv_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "opencv_dependency_available", lambda: False)

        with pytest.raises(VisionDependencyUnavailableError):
            detectors.detect_faces(Image.new("RGB", (10, 10)))

    def test_maps_cascade_detections_into_face_regions(self, monkeypatch) -> None:
        class _FakeCascade:
            def empty(self) -> bool:
                return False

            def detectMultiScale(self, *args, **kwargs):
                return [(5, 10, 40, 45)]

        monkeypatch.setattr(cv2, "CascadeClassifier", lambda *_: _FakeCascade())

        faces = detectors.detect_faces(Image.new("RGB", (200, 200)))

        assert faces == (
            detectors.FaceRegion(x=5, y=10, width=40, height=45),
        )


class TestDetectQrCodes:
    def test_decodes_a_real_generated_qr_code(self) -> None:
        image = qrcode.make("https://example.com/parika-test").convert("RGB")

        results = detectors.detect_qr_codes(image)

        assert len(results) == 1
        assert results[0].data == "https://example.com/parika-test"
        assert results[0].symbology == "QRCODE"

    def test_returns_empty_tuple_for_an_image_without_a_qr_code(self) -> None:
        blank = Image.new("RGB", (100, 100), color=(255, 255, 255))

        assert detectors.detect_qr_codes(blank) == ()

    def test_raises_when_pyzbar_unavailable(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "pyzbar_dependency_available", lambda: False)

        with pytest.raises(VisionDependencyUnavailableError):
            detectors.detect_qr_codes(Image.new("RGB", (10, 10)))


class TestDetectBarcodes:
    def test_decodes_a_real_generated_barcode(self) -> None:
        from barcode.writer import ImageWriter

        code = barcode.get("code128", "PARIKA-123", writer=ImageWriter())
        buffer = __import__("io").BytesIO()
        code.write(buffer)
        buffer.seek(0)
        image = Image.open(buffer).convert("RGB")

        results = detectors.detect_barcodes(image)

        assert len(results) == 1
        assert results[0].data == "PARIKA-123"
        assert results[0].symbology == "CODE128"

    def test_excludes_qr_codes(self) -> None:
        image = qrcode.make("not a barcode").convert("RGB")

        assert detectors.detect_barcodes(image) == ()


class TestCountBlobs:
    def test_counts_separated_blobs_on_a_plain_background(self) -> None:
        image = Image.new("L", (300, 300), color=255)
        draw = ImageDraw.Draw(image)

        for cx in (40, 100, 160, 220, 280):
            draw.ellipse([cx - 15, 140, cx + 15, 170], fill=0)

        result = detectors.count_blobs(image.convert("RGB"))

        assert result.count == 5
        assert result.is_confident

    def test_dense_checkerboard_is_flagged_as_not_confident(self) -> None:
        # A dense, diagonally-isolated checkerboard produces far more
        # 4-connected foreground regions than any real "count the
        # objects" scene would -- exactly the kind of texture this
        # heuristic must recognize it cannot trust (it hits
        # `regions.label_regions()`'s own `max_regions` cap).
        cell = 8
        image = Image.new("L", (200, 200), color=255)
        pixels = image.load()

        for y in range(200):
            for x in range(200):
                if (x // cell + y // cell) % 2 == 0:
                    pixels[x, y] = 0

        result = detectors.count_blobs(image.convert("RGB"))

        assert not result.is_confident


class TestClassifyImageHeuristic:
    def test_labels_are_always_one_of_the_known_categories(self) -> None:
        ui = Image.new("RGB", (400, 300), color=(245, 245, 245))
        draw = ImageDraw.Draw(ui)
        draw.rectangle([10, 10, 390, 50], fill=(220, 220, 220))

        result = detectors.classify_image_heuristic(ui)

        assert result.label in detectors._CLASSIFICATION_LABELS
        assert 0.0 <= result.confidence <= 1.0
        assert set(result.scores) == set(detectors._CLASSIFICATION_LABELS)

    def test_high_color_cardinality_image_favors_photograph(self) -> None:
        import numpy as np

        rng = np.random.default_rng(seed=7)
        colorful = Image.fromarray(
            (rng.random((256, 256, 3)) * 255).astype("uint8")
        )

        result = detectors.classify_image_heuristic(colorful)

        assert result.scores["photograph"] > result.scores["screenshot_or_ui"]
