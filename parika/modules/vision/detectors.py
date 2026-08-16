"""
PARIKA Vision Module - Deterministic Face/Code/Blob Detectors & Heuristic Classifier

Classical, non-learned-model-per-request computer vision detectors --
never a Vision Language Model call:

- `detect_faces()` -- OpenCV's bundled Haar-cascade frontal-face
  detector (`cv2.CascadeClassifier`), the textbook "QR detection ->
  QR libraries"-style guidance applied to faces: a real, decades-old,
  shipped-with-the-library classical detector, not a neural network
  downloaded per call.
- `detect_qr_codes()`/`detect_barcodes()` -- ZBar, via `pyzbar`, the
  standard deterministic decoder for both symbologies (one library,
  not two) -- exactly the task's own "QR detection -> QR libraries",
  "Barcode detection -> barcode libraries" guidance.
- `count_blobs()` -- Otsu-thresholding plus `regions.label_regions()`
  connected-component counting -- "Object counting -> object
  detector output" taken as literally as a *classical* detector
  (rather than a trained one) allows: reliable for simple, high-
  contrast foreground-on-background scenes (parts on a table, cells
  on a slide), not for cluttered natural photographs, which is
  exactly why `vision.count_objects`'s ToolDriver only trusts this
  path when it looks confident and falls back to a Provider-backed
  Vision model otherwise.
- `classify_image_heuristic()` -- a cheap, deterministic image-*type*
  classifier (screenshot/UI, document/text-like, graphic/illustration,
  photograph) from edge density, color-cardinality, and uniform-region
  statistics -- genuinely useful for the coarse "what kind of image is
  this" question without any model call; open-set semantic labels
  (e.g. "cat" vs "dog") remain out of reach for a heuristic and are
  exactly what `vision.classify_image` falls back to its Provider-
  backed Capability for.

`detect_faces()` requires the optional `vision` dependency group
(`opencv-python-headless`); `detect_qr_codes()`/`detect_barcodes()`
require `pyzbar` (plus the system ZBar library) -- both raise
`VisionDependencyUnavailableError` up front (via `config.require_*()`)
when unavailable, exactly like OCR's own `require_imaging()` pattern.
`count_blobs()`/`classify_image_heuristic()` need only Pillow/numpy
(always available).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import regions
from .config import require_opencv, require_pyzbar

if TYPE_CHECKING:
    from PIL.Image import Image

DEFAULT_BLOB_MIN_AREA = 40
DEFAULT_FACE_MIN_SIZE = 30
_CLASSIFY_RESIZE = (256, 256)


@dataclass(frozen=True, slots=True, kw_only=True)
class FaceRegion:
    """One detected face's bounding box."""

    x: int
    y: int
    width: int
    height: int


def detect_faces(image: "Image") -> tuple[FaceRegion, ...]:
    """
    Detect frontal faces via OpenCV's bundled Haar-cascade classifier
    (`haarcascade_frontalface_default.xml`, shipped with
    `opencv-python-headless`) -- a real, classical, non-learned-per-
    call detector; never a Vision Language Model call. Requires the
    optional `vision` dependency group.
    """

    require_opencv()

    import cv2
    import numpy as np

    grayscale = np.asarray(image.convert("L"))
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"  # type: ignore[attr-defined]
    cascade = cv2.CascadeClassifier(cascade_path)

    if cascade.empty():
        return ()

    detections = cascade.detectMultiScale(
        grayscale,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(DEFAULT_FACE_MIN_SIZE, DEFAULT_FACE_MIN_SIZE),
    )

    return tuple(
        FaceRegion(x=int(x), y=int(y), width=int(w), height=int(h))
        for x, y, w, h in detections
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CodeResult:
    """One decoded QR code/barcode's payload, symbology, and bounding box."""

    data: str
    symbology: str
    x: int
    y: int
    width: int
    height: int


def _decode_with_zbar(image: "Image") -> tuple:
    require_pyzbar()

    from pyzbar import pyzbar

    return pyzbar.decode(image.convert("L"))


def detect_qr_codes(image: "Image") -> tuple[CodeResult, ...]:
    """
    Decode every QR code in `image` via ZBar (`pyzbar`) -- a real
    deterministic decoder library, never a Vision Language Model
    call. Requires the optional `vision` dependency group.
    """

    results = _decode_with_zbar(image)

    return tuple(
        CodeResult(
            data=result.data.decode("utf-8", errors="replace"),
            symbology=str(result.type),
            x=int(result.rect.left),
            y=int(result.rect.top),
            width=int(result.rect.width),
            height=int(result.rect.height),
        )
        for result in results
        if str(result.type) == "QRCODE"
    )


def detect_barcodes(image: "Image") -> tuple[CodeResult, ...]:
    """
    Decode every 1D/2D barcode (EAN, UPC, Code128, ...; excluding QR
    codes -- see `detect_qr_codes()`) in `image` via ZBar (`pyzbar`).
    Requires the optional `vision` dependency group.
    """

    results = _decode_with_zbar(image)

    return tuple(
        CodeResult(
            data=result.data.decode("utf-8", errors="replace"),
            symbology=str(result.type),
            x=int(result.rect.left),
            y=int(result.rect.top),
            width=int(result.rect.width),
            height=int(result.rect.height),
        )
        for result in results
        if str(result.type) != "QRCODE"
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class BlobCountResult:
    """Deterministic blob/connected-component count -- see `count_blobs()`."""

    count: int
    regions: tuple[regions.BoundingBox, ...]
    is_confident: bool


def count_blobs(
    image: "Image", *, min_area: int = DEFAULT_BLOB_MIN_AREA
) -> BlobCountResult:
    """
    Deterministic foreground-blob count: Otsu-style thresholding
    (numpy histogram-variance search -- no `scipy`/`opencv` needed)
    against a downscaled grayscale copy, then `regions.label_regions()`
    connected-component counting. Reliable only for simple, high-
    contrast foreground-on-background images; `is_confident` is
    `False` whenever the foreground covers an implausibly large or
    small fraction of the frame (>60% or <0.1%) -- the two clearest
    "this heuristic does not apply here" signals -- so callers
    (`vision.count_objects`'s ToolDriver) know to fall back to a
    Provider-backed Vision model instead of trusting a meaningless
    count.
    """

    import numpy as np

    grayscale = image.convert("L")
    grayscale.thumbnail((400, 400))
    array = np.asarray(grayscale, dtype=np.uint8)

    threshold = _otsu_threshold(array)
    dark_ratio = float((array <= threshold).mean())
    # Whichever side (darker-than-or-equal-to-threshold, or lighter)
    # is the minority is assumed to be the foreground -- a plain
    # background is typically the majority color.
    foreground_mask = (
        (array <= threshold) if dark_ratio <= 0.5 else (array > threshold)
    )
    foreground_ratio = float(foreground_mask.mean())

    boxes = regions.label_regions(foreground_mask, min_area=min_area, max_regions=200)

    # A background/foreground split that is plausible in *ratio* can
    # still be meaningless noise if it produces an implausibly large
    # number of tiny regions (e.g. random noise, dense texture) --
    # `regions.label_regions()`'s own `max_regions=200` cap being hit
    # is itself the clearest such signal.
    is_confident = (
        0.001 <= foreground_ratio <= 0.6
        and 0 < len(boxes) < 200
    )

    return BlobCountResult(
        count=len(boxes), regions=boxes, is_confident=is_confident
    )


def _otsu_threshold(array) -> int:
    """Plain numpy Otsu threshold: the intensity level maximizing between-class variance."""

    import numpy as np

    histogram, _ = np.histogram(array, bins=256, range=(0, 256))
    total = array.size

    if total == 0:
        return 128

    sum_all = float(np.dot(histogram, np.arange(256)))
    sum_background = 0.0
    weight_background = 0
    best_variance = -1.0
    best_threshold = 128

    for level in range(256):
        weight_background += histogram[level]
        if weight_background == 0:
            continue

        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break

        sum_background += level * histogram[level]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground

        variance = (
            weight_background
            * weight_foreground
            * (mean_background - mean_foreground) ** 2
        )

        if variance > best_variance:
            best_variance = variance
            best_threshold = level

    return best_threshold


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassificationResult:
    """Heuristic image-type classification -- see `classify_image_heuristic()`."""

    label: str
    confidence: float
    scores: dict


_CLASSIFICATION_LABELS = (
    "screenshot_or_ui",
    "document_or_text",
    "graphic_or_illustration",
    "photograph",
)


def classify_image_heuristic(image: "Image") -> ClassificationResult:
    """
    Cheap, deterministic image-*type* classification into one of
    `_CLASSIFICATION_LABELS`, from edge density, distinct-color
    cardinality, and uniform-region fraction -- no model call.
    Screenshots/UI and documents both have very few distinct colors
    and large uniform regions (flat fills/background), but documents
    have much higher edge density (dense text) than typical UI chrome;
    photographs have many distinct colors and only a moderate uniform
    fraction; anything with few colors and low edge density but no
    strongly dominant single color reads as a simple graphic/
    illustration. This is a real, honest heuristic for coarse image
    *type*, never open-set semantic labels (e.g. specific objects/
    brands/scenes) -- `vision.classify_image`'s ToolDriver falls back
    to its Provider-backed Capability whenever the caller supplies
    open-set candidate labels.
    """

    import numpy as np

    resized = image.convert("RGB").resize(_CLASSIFY_RESIZE)
    array = np.asarray(resized, dtype=np.int32)

    quantized = (array // 32) * 32
    flat = quantized.reshape(-1, 3)
    distinct_colors = len({tuple(pixel) for pixel in flat.tolist()})

    grayscale = np.asarray(resized.convert("L"), dtype=np.float64)
    gradient_x = np.abs(np.diff(grayscale, axis=1))
    gradient_y = np.abs(np.diff(grayscale, axis=0))
    edge_density = float((gradient_x.mean() + gradient_y.mean()) / 2.0) / 255.0

    values, counts = np.unique(flat, axis=0, return_counts=True)
    uniform_fraction = float(counts.max() / flat.shape[0])

    scores = {
        "screenshot_or_ui": (
            max(0.0, 1.0 - min(1.0, distinct_colors / 400.0)) * 0.5
            + uniform_fraction * 0.3
            + max(0.0, 1.0 - edge_density * 8.0) * 0.2
        ),
        "document_or_text": (
            max(0.0, 1.0 - min(1.0, distinct_colors / 200.0)) * 0.4
            + min(1.0, edge_density * 10.0) * 0.5
            + uniform_fraction * 0.1
        ),
        "graphic_or_illustration": (
            max(0.0, 1.0 - min(1.0, distinct_colors / 600.0)) * 0.4
            + max(0.0, 1.0 - uniform_fraction) * 0.3
            + max(0.0, 1.0 - edge_density * 8.0) * 0.3
        ),
        "photograph": (
            min(1.0, distinct_colors / 800.0) * 0.6
            + max(0.0, 1.0 - uniform_fraction) * 0.4
        ),
    }

    ordered = sorted(scores.items(), key=lambda item: -item[1])
    best_label, best_score = ordered[0]
    total = sum(scores.values()) or 1.0
    margin = (best_score - ordered[1][1]) / total if len(ordered) > 1 else 1.0

    return ClassificationResult(
        label=best_label,
        confidence=round(max(0.0, min(1.0, margin * 2)), 4),
        scores={label: round(score, 4) for label, score in scores.items()},
    )
