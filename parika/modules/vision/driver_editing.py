"""
PARIKA Vision Module - Deterministic Editing Drivers (Phase 5)

Every driver here reads a source image through the existing,
unmodified `filesystem.read` Capability, applies a pure Pillow
transform (`editing.py`), and writes the result back out through the
existing, unmodified `filesystem.write` Capability
(`engine.write_image_base64()`) -- never a model call, for any of
`vision.crop_image`, `vision.resize_image`, `vision.rotate_image`,
`vision.flip_image`, `vision.convert_format`, or
`vision.compress_image` (none of which even register a
`vision.provider_*` Capability -- purely deterministic, per this
Module's frozen naming convention).

`vision.enhance_image` and `vision.remove_background` are the two
Phase 5 Capabilities that *do* register a `vision.provider_*`
Capability: both still run a deterministic pipeline by default
(`editing.enhance()`/`segmentation.remove_background()`), and only
additionally consult their Provider-backed Capability -- for a short
semantic note, never to alter the deterministic pixels themselves --
when the caller supplies a non-empty `instruction`, exactly the same
opt-in escalation shape every other hybrid driver in this Module
uses.
"""

from __future__ import annotations

import os

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import editing, engine, segmentation
from .exceptions import VisionImageReadError


def _require_path(request: ToolRequest) -> str:
    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise VisionImageReadError(
            "request.arguments['path'] must be a non-empty string."
        )

    return path


def _default_output_path(path: str, suffix: str, *, new_extension: str | None = None) -> str:
    root, extension = os.path.splitext(path)
    extension = f".{new_extension.lower()}" if new_extension else extension
    return f"{root}{suffix}{extension}"


def _format_for_path(path: str, *, default: str = "PNG") -> str:
    extension = os.path.splitext(path)[1].lstrip(".").upper()
    return {"JPG": "JPEG"}.get(extension, extension) or default


class VisionCropImageToolDriver:
    """`ToolDriver` implementing `vision.crop_image`."""

    def __init__(self, *, brain, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("vision.crop_image")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        x = int(request.arguments.get("x", 0))
        y = int(request.arguments.get("y", 0))
        width = int(request.arguments.get("width", 0))
        height = int(request.arguments.get("height", 0))
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(path, "_cropped")
        )

        self._progress.started(message="Reading image...")
        image = engine.decode_base64_image(engine.read_image_base64(self._brain, path))

        self._progress.progress(message="Cropping...")
        cropped = editing.crop(image, x=x, y=y, width=width, height=height)

        self._progress.progress(message="Writing image...")
        output_format = _format_for_path(output_path, default=image.format or "PNG")
        engine.write_image_base64(
            self._brain, output_path, engine.encode_image_base64(cropped, image_format=output_format)
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "output_path": output_path,
                "width": cropped.width,
                "height": cropped.height,
            },
            attributes={"path": path},
        )


class VisionResizeImageToolDriver:
    """`ToolDriver` implementing `vision.resize_image`."""

    def __init__(self, *, brain, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("vision.resize_image")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        width = request.arguments.get("width")
        height = request.arguments.get("height")
        scale = request.arguments.get("scale")
        keep_aspect_ratio = bool(request.arguments.get("keep_aspect_ratio", True))
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(path, "_resized")
        )

        self._progress.started(message="Reading image...")
        image = engine.decode_base64_image(engine.read_image_base64(self._brain, path))

        self._progress.progress(message="Resizing...")
        resized = editing.resize(
            image,
            width=int(width) if width is not None else None,
            height=int(height) if height is not None else None,
            scale=float(scale) if scale is not None else None,
            keep_aspect_ratio=keep_aspect_ratio,
        )

        self._progress.progress(message="Writing image...")
        output_format = _format_for_path(output_path, default=image.format or "PNG")
        engine.write_image_base64(
            self._brain, output_path, engine.encode_image_base64(resized, image_format=output_format)
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "output_path": output_path,
                "width": resized.width,
                "height": resized.height,
            },
            attributes={"path": path},
        )


class VisionRotateImageToolDriver:
    """`ToolDriver` implementing `vision.rotate_image`."""

    def __init__(self, *, brain, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("vision.rotate_image")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        degrees = float(request.arguments.get("degrees", 0.0))
        expand = bool(request.arguments.get("expand", True))
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(path, "_rotated")
        )

        self._progress.started(message="Reading image...")
        image = engine.decode_base64_image(engine.read_image_base64(self._brain, path))

        self._progress.progress(message="Rotating...")
        rotated = editing.rotate(image, degrees, expand=expand)

        self._progress.progress(message="Writing image...")
        output_format = _format_for_path(output_path, default=image.format or "PNG")
        engine.write_image_base64(
            self._brain, output_path, engine.encode_image_base64(rotated, image_format=output_format)
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "output_path": output_path,
                "width": rotated.width,
                "height": rotated.height,
            },
            attributes={"path": path},
        )


class VisionFlipImageToolDriver:
    """`ToolDriver` implementing `vision.flip_image`."""

    def __init__(self, *, brain, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("vision.flip_image")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        direction = str(request.arguments.get("direction", "horizontal")).strip().lower()

        if direction not in ("horizontal", "vertical"):
            raise VisionImageReadError(
                "request.arguments['direction'] must be 'horizontal' or 'vertical'."
            )

        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(path, "_flipped")
        )

        self._progress.started(message="Reading image...")
        image = engine.decode_base64_image(engine.read_image_base64(self._brain, path))

        self._progress.progress(message="Flipping...")
        flipped = editing.flip(image, direction=direction)  # type: ignore[arg-type]

        self._progress.progress(message="Writing image...")
        output_format = _format_for_path(output_path, default=image.format or "PNG")
        engine.write_image_base64(
            self._brain, output_path, engine.encode_image_base64(flipped, image_format=output_format)
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"output_path": output_path},
            attributes={"path": path},
        )


class VisionEnhanceImageToolDriver:
    """`ToolDriver` implementing `vision.enhance_image`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._progress = progress_reporter or NullProgressReporter("vision.enhance_image")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        instruction = str(request.arguments.get("instruction", "")).strip()
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(path, "_enhanced")
        )

        self._progress.started(message="Reading image...")
        image_base64 = engine.read_image_base64(self._brain, path)
        image = engine.decode_base64_image(image_base64)

        self._progress.progress(message="Enhancing...")
        enhanced = editing.enhance(
            image,
            autocontrast=bool(request.arguments.get("autocontrast", True)),
            sharpen=bool(request.arguments.get("sharpen", True)),
            denoise=bool(request.arguments.get("denoise", False)),
        )

        self._progress.progress(message="Writing image...")
        output_format = _format_for_path(output_path, default="PNG")
        engine.write_image_base64(
            self._brain, output_path, engine.encode_image_base64(enhanced, image_format=output_format)
        )

        result: dict = {"output_path": output_path}

        if instruction:
            self._progress.progress(message="Waiting for Vision model...")
            result["notes"] = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (image_base64,),
                (
                    "Suggest, in one or two sentences, what further "
                    f"visual enhancement would achieve: {instruction}"
                ),
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result=result, attributes={"path": path})


class VisionRemoveBackgroundToolDriver:
    """`ToolDriver` implementing `vision.remove_background`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._progress = progress_reporter or NullProgressReporter(
            "vision.remove_background"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        instruction = str(request.arguments.get("instruction", "")).strip()
        margin_ratio = float(request.arguments.get("margin_ratio", 0.05))
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(path, "_no_bg", new_extension="png")
        )

        self._progress.started(message="Reading image...")
        image_base64 = engine.read_image_base64(self._brain, path)
        image = engine.decode_base64_image(image_base64)

        self._progress.progress(message="Removing background...")
        result_image = segmentation.remove_background(image, margin_ratio=margin_ratio)

        self._progress.progress(message="Writing image...")
        engine.write_image_base64(
            self._brain, output_path, engine.encode_image_base64(result_image, image_format="PNG")
        )

        result: dict = {"output_path": output_path}

        if instruction:
            self._progress.progress(message="Waiting for Vision model...")
            result["notes"] = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (image_base64,),
                f"Regarding this image: {instruction}",
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result=result, attributes={"path": path})


class VisionConvertFormatToolDriver:
    """`ToolDriver` implementing `vision.convert_format`."""

    def __init__(self, *, brain, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("vision.convert_format")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        target_format = str(request.arguments.get("target_format", "")).strip().upper()

        if not target_format:
            raise VisionImageReadError(
                "request.arguments['target_format'] must be a non-empty string."
            )

        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(
                path, "", new_extension=target_format.lower().replace("jpeg", "jpg")
            )
        )

        self._progress.started(message="Reading image...")
        image = engine.decode_base64_image(engine.read_image_base64(self._brain, path))

        self._progress.progress(message="Converting...")
        converted = editing.convert_format(image, target_format)

        self._progress.progress(message="Writing image...")
        engine.write_image_base64(
            self._brain,
            output_path,
            engine.encode_image_base64(converted, image_format=target_format),
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"output_path": output_path, "format": target_format},
            attributes={"path": path},
        )


class VisionCompressImageToolDriver:
    """`ToolDriver` implementing `vision.compress_image`."""

    def __init__(
        self,
        *,
        brain,
        progress_reporter: ProgressReporter | None = None,
        default_quality: int = 75,
    ) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("vision.compress_image")
        self._default_quality = default_quality

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        quality = int(request.arguments.get("quality", self._default_quality))
        target_format = str(
            request.arguments.get("target_format", "JPEG")
        ).strip().upper()
        output_path = str(
            request.arguments.get("output_path")
            or _default_output_path(
                path, "_compressed", new_extension=target_format.lower().replace("jpeg", "jpg")
            )
        )

        self._progress.started(message="Reading image...")
        payload = engine.read_image_payload(self._brain, path)
        image = engine.decode_base64_image(str(payload["content_base64"]))
        bytes_before = int(payload.get("size", 0))

        self._progress.progress(message="Compressing...")
        prepared = editing.convert_format(image, target_format)
        encoded_base64 = engine.encode_image_base64(
            prepared,
            image_format=target_format,
            quality=quality if target_format in ("JPEG", "WEBP") else None,
        )
        bytes_after = len(encoded_base64) * 3 // 4

        self._progress.progress(message="Writing image...")
        engine.write_image_base64(self._brain, output_path, encoded_base64)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "output_path": output_path,
                "bytes_before": bytes_before,
                "bytes_after": bytes_after,
            },
            attributes={"path": path},
        )
