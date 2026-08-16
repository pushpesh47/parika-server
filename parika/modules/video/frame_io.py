"""
PARIKA Video Module - Deterministic Frame Decoding

`cv2.VideoCapture`-based video container decoding -- no model call,
no Brain/Goal/Capability concept. This is the one place in the
Module allowed to open a real filesystem path directly with a
third-party decoder, because video demuxing/decoding (unlike a
single-shot image read) genuinely requires a real, seekable file
handle; `cv2.VideoCapture` has no supported in-memory-buffer input
for compressed containers. `engine.py`'s `resolve_video_path()`
still validates the path through the existing, unmodified
`filesystem.info` Capability (permission-checked, existence-checked)
*before* any function here ever touches it -- see that module's own
docstring for the full rationale.

Every function here is pure decoding -- no algorithm (sampling
strategy, blur/scene/motion detection, ...) lives here.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from .config import require_opencv
from .exceptions import VideoDecodeError, VideoFrameExtractionError

if TYPE_CHECKING:
    from PIL.Image import Image


@dataclass(frozen=True, slots=True, kw_only=True)
class VideoProperties:
    """Raw container-level properties reported by `cv2.VideoCapture`."""

    frame_rate: float | None
    frame_count: int | None
    width: int | None
    height: int | None
    fourcc: str | None


def _fourcc_to_str(fourcc_code: float) -> str | None:
    code = int(fourcc_code)

    if code <= 0:
        return None

    chars = "".join(chr((code >> (8 * index)) & 0xFF) for index in range(4))
    cleaned = chars.strip().strip("\x00")
    return cleaned or None


def open_capture(resolved_path: str):
    """
    Open `resolved_path` (already validated through
    `engine.resolve_video_path()`) with `cv2.VideoCapture`. Raises
    `VideoDecodeError` when the container cannot be opened at all
    (missing/corrupt file, unsupported/missing codec).
    """

    require_opencv()

    import cv2

    capture = cv2.VideoCapture(resolved_path)

    if not capture.isOpened():
        capture.release()
        raise VideoDecodeError(
            f"Could not open video container at '{resolved_path}' -- "
            "the file may be corrupted, empty, or use an unsupported "
            "codec."
        )

    return capture


def read_properties(capture) -> VideoProperties:
    """
    Read `capture`'s container-level properties. Any property OpenCV
    cannot determine (0 or negative) is reported as `None` rather
    than a misleading `0`.
    """

    import cv2

    def _positive_float(value: float) -> float | None:
        return value if value and value > 0 else None

    def _positive_int(value: float) -> int | None:
        return int(value) if value and value > 0 else None

    frame_rate = _positive_float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = _positive_int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = _positive_int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = _positive_int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = _fourcc_to_str(capture.get(cv2.CAP_PROP_FOURCC))

    return VideoProperties(
        frame_rate=frame_rate,
        frame_count=frame_count,
        width=width,
        height=height,
        fourcc=fourcc,
    )


def _bgr_array_to_image(array) -> "Image":
    import cv2
    from PIL import Image as PILImage

    rgb = cv2.cvtColor(array, cv2.COLOR_BGR2RGB)
    return PILImage.fromarray(rgb)


def decode_frame_at(capture, frame_index: int) -> "Image":
    """
    Seek `capture` to `frame_index` and decode it into a Pillow
    `Image` (RGB). Raises `VideoFrameExtractionError` when the seek
    or the read itself fails (e.g. `frame_index` beyond the last
    decodable frame -- containers' reported `frame_count` is
    sometimes an estimate).
    """

    import cv2

    if not capture.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index)):
        raise VideoFrameExtractionError(
            f"Could not seek to frame {frame_index}."
        )

    success, array = capture.read()

    if not success or array is None:
        raise VideoFrameExtractionError(
            f"Could not decode frame {frame_index}."
        )

    return _bgr_array_to_image(array)


@dataclass(frozen=True, slots=True, kw_only=True)
class DecodedFrame:
    """One successfully decoded frame -- index, timestamp, and pixels."""

    index: int
    timestamp_seconds: float
    image: "Image"


def extract_frames(
    resolved_path: str,
    frame_indices: Iterable[int],
    *,
    frame_rate: float | None,
) -> list[DecodedFrame]:
    """
    Decode every index in `frame_indices` (deduplicated, ascending --
    monotonic seeks are far cheaper than random access for most
    container/codec combinations) from `resolved_path`, opening the
    container exactly once. Indices that fail to decode (see
    `decode_frame_at()`) are silently skipped rather than aborting
    the whole batch, since a handful of undecodable frames near the
    end of an estimated `frame_count` is a common, benign case.
    """

    ordered_indices = sorted({max(0, int(index)) for index in frame_indices})

    if not ordered_indices:
        return []

    capture = open_capture(resolved_path)
    decoded: list[DecodedFrame] = []

    try:
        for index in ordered_indices:
            try:
                image = decode_frame_at(capture, index)
            except VideoFrameExtractionError:
                continue

            timestamp = (index / frame_rate) if frame_rate else 0.0
            decoded.append(
                DecodedFrame(index=index, timestamp_seconds=round(timestamp, 3), image=image)
            )
    finally:
        capture.release()

    return decoded


def encode_frame_base64(
    image: "Image", *, image_format: str = "JPEG", quality: int = 85
) -> str:
    """
    Encode a decoded frame to a base64 string for a nested Provider
    Goal's provider-independent `ChatMessage.images` tuple (`parika
    /core/provider_manager/chat_message.py`) -- exactly the same shape
    `vision/engine.py`'s `encode_image_base64()` produces for images
    obtained via `filesystem.read`.
    """

    buffer = io.BytesIO()
    to_save = image.convert("RGB") if image_format.upper() in ("JPEG", "JPG") else image
    save_kwargs: dict = {"format": image_format}

    if image_format.upper() in ("JPEG", "JPG"):
        save_kwargs["quality"] = quality

    to_save.save(buffer, **save_kwargs)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def decode_base64_image(image_base64: str) -> "Image":
    """Decode a base64-encoded image (e.g. a thumbnail input) into a Pillow `Image`."""

    from PIL import Image as PILImage

    raw_bytes = base64.b64decode(image_base64)
    image = PILImage.open(io.BytesIO(raw_bytes))
    image.load()
    return image
