"""
PARIKA Vision Module - Configuration

Reads the `[vision]` configuration section and detects, at runtime,
whether each optional deterministic dependency is installed:
`opencv-python-headless` (Haar-cascade face detection, classical
GrabCut background segmentation) and `pyzbar` (ZBar-backed QR/barcode
decoding). Mirrors exactly the pattern `parika/modules/ocr/config.py`
already establishes for the `ocr` extra's `Pillow`/`numpy` pair.

Every deterministic Capability that only needs `Pillow`/`numpy`
(comparison/hashing, difference regions, blur/rotation/quality/
anomaly detection, basic editing) always works, since both are
already base dependencies (`pyproject.toml`) -- exactly like
`ocr.provider_extract_text` always working regardless of the `ocr`
extra. Only face/QR/barcode detection and GrabCut-based background
removal are gracefully skipped (never a crash, a clear
`VisionDependencyUnavailableError` instead) when the optional
`vision` dependency group is not installed.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

from .exceptions import VisionDependencyUnavailableError

DEFAULT_ENABLED = True
DEFAULT_HASH_SIZE = 8
DEFAULT_SIMILARITY_THRESHOLD = 0.90
DEFAULT_DUPLICATE_HAMMING_DISTANCE = 5
DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0
DEFAULT_LOW_RESOLUTION_MIN_DIMENSION = 1000
DEFAULT_QUALITY_SCORE_MINIMUM = 0.5
DEFAULT_ANOMALY_Z_SCORE_THRESHOLD = 2.5
DEFAULT_MAX_SEARCH_CANDIDATES = 20
DEFAULT_JPEG_COMPRESS_QUALITY = 75


def opencv_dependency_available() -> bool:
    """
    Whether the optional `opencv-python-headless` dependency (Haar-
    cascade face detection, classical GrabCut background segmentation)
    is installed.
    """

    return importlib.util.find_spec("cv2") is not None


def pyzbar_dependency_available() -> bool:
    """
    Whether the optional `pyzbar` dependency (ZBar-backed QR/barcode
    decoding) is installed.
    """

    return importlib.util.find_spec("pyzbar") is not None


def require_opencv() -> None:
    """
    Raise `VisionDependencyUnavailableError` unless the optional
    `opencv-python-headless` dependency is installed. Shared by every
    Capability in this Module that needs it (`detectors.py`'s
    `detect_faces()`, `segmentation.py`'s `remove_background()`).
    """

    if not opencv_dependency_available():
        raise VisionDependencyUnavailableError(
            "This Vision feature requires the optional 'vision' "
            "dependency group (opencv-python-headless) to be "
            "installed."
        )


def require_pyzbar() -> None:
    """
    Raise `VisionDependencyUnavailableError` unless the optional
    `pyzbar` dependency (and its underlying system ZBar shared
    library) is installed. Shared by `detectors.py`'s
    `detect_qr_codes()`/`detect_barcodes()`.
    """

    if not pyzbar_dependency_available():
        raise VisionDependencyUnavailableError(
            "This Vision feature requires the optional 'vision' "
            "dependency group (pyzbar, plus the system ZBar shared "
            "library) to be installed."
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionToolConfig:
    """
    Immutable, typed snapshot of `[vision]` configuration.
    """

    enabled: bool = DEFAULT_ENABLED
    hash_size: int = DEFAULT_HASH_SIZE
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    duplicate_hamming_distance: int = DEFAULT_DUPLICATE_HAMMING_DISTANCE
    blur_variance_threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD
    low_resolution_min_dimension: int = DEFAULT_LOW_RESOLUTION_MIN_DIMENSION
    quality_score_minimum: float = DEFAULT_QUALITY_SCORE_MINIMUM
    anomaly_z_score_threshold: float = DEFAULT_ANOMALY_Z_SCORE_THRESHOLD
    max_search_candidates: int = DEFAULT_MAX_SEARCH_CANDIDATES
    jpeg_compress_quality: int = DEFAULT_JPEG_COMPRESS_QUALITY

    @property
    def face_detection_available(self) -> bool:
        """Whether `vision.detect_faces`'s deterministic path is installed."""

        return opencv_dependency_available()

    @property
    def background_removal_available(self) -> bool:
        """Whether `vision.remove_background`'s deterministic path is installed."""

        return opencv_dependency_available()

    @property
    def code_detection_available(self) -> bool:
        """Whether `vision.detect_qr_codes`/`vision.detect_barcodes` are installed."""

        return pyzbar_dependency_available()


def load_vision_config(configuration: Configuration | None) -> VisionToolConfig:
    """
    Build a `VisionToolConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return VisionToolConfig()

    return VisionToolConfig(
        enabled=bool(configuration.get("vision.enabled", DEFAULT_ENABLED)),
        hash_size=int(configuration.get("vision.hash_size", DEFAULT_HASH_SIZE)),
        similarity_threshold=float(
            configuration.get(
                "vision.similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD
            )
        ),
        duplicate_hamming_distance=int(
            configuration.get(
                "vision.duplicate_hamming_distance",
                DEFAULT_DUPLICATE_HAMMING_DISTANCE,
            )
        ),
        blur_variance_threshold=float(
            configuration.get(
                "vision.blur_variance_threshold", DEFAULT_BLUR_VARIANCE_THRESHOLD
            )
        ),
        low_resolution_min_dimension=int(
            configuration.get(
                "vision.low_resolution_min_dimension",
                DEFAULT_LOW_RESOLUTION_MIN_DIMENSION,
            )
        ),
        quality_score_minimum=float(
            configuration.get(
                "vision.quality_score_minimum", DEFAULT_QUALITY_SCORE_MINIMUM
            )
        ),
        anomaly_z_score_threshold=float(
            configuration.get(
                "vision.anomaly_z_score_threshold",
                DEFAULT_ANOMALY_Z_SCORE_THRESHOLD,
            )
        ),
        max_search_candidates=int(
            configuration.get(
                "vision.max_search_candidates", DEFAULT_MAX_SEARCH_CANDIDATES
            )
        ),
        jpeg_compress_quality=int(
            configuration.get(
                "vision.jpeg_compress_quality", DEFAULT_JPEG_COMPRESS_QUALITY
            )
        ),
    )
