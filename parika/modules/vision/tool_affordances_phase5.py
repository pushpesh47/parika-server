"""
PARIKA Vision Module - Tool Affordance Contracts (Phase 5)

Tool Affordance Contracts for the deterministic editing Capabilities:
`vision.crop_image`, `vision.resize_image`, `vision.rotate_image`,
`vision.flip_image`, `vision.enhance_image`, `vision.remove_background`,
`vision.convert_format`, and `vision.compress_image` -- split out of
`module_driver.py` purely to keep that file within the project's File
Size Guidelines.
"""

from __future__ import annotations

from typing import Any, Mapping

_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the source image.",
}
_OUTPUT_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": (
        "Where to write the result. Optional; defaults to a sibling "
        "file next to the source image."
    ),
}

VISION_CROP_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically crops a local image to a pixel rectangle and writes the result. Never calls a model.",
    "use_when": "the user wants a specific region of an image extracted/cropped.",
    "avoid_when": "the user wants the whole image resized instead (use `vision_resize_image`).",
    "requires": "the image path and the crop rectangle (x, y, width, height); ask the user for whichever is missing.",
    "result_semantics": "Returns the written output_path and the cropped dimensions.",
    "failure_semantics": "If the image cannot be read or the result cannot be written, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "x": {"type": "integer", "description": "Left edge of the crop rectangle, in pixels."},
            "y": {"type": "integer", "description": "Top edge of the crop rectangle, in pixels."},
            "width": {"type": "integer", "description": "Crop rectangle width, in pixels."},
            "height": {"type": "integer", "description": "Crop rectangle height, in pixels."},
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path", "x", "y", "width", "height"],
    },
}

VISION_RESIZE_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically resizes a local image (by width/height and/or scale factor) and writes the result. Never calls a model.",
    "use_when": "the user wants an image made larger/smaller.",
    "avoid_when": "the user wants a specific region extracted instead (use `vision_crop_image`).",
    "requires": "the image path and at least one of width/height/scale; ask the user for whichever is missing.",
    "result_semantics": "Returns the written output_path and the resulting dimensions.",
    "failure_semantics": "If the image cannot be read or the result cannot be written, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "width": {"type": "integer", "description": "Target width, in pixels. Optional."},
            "height": {"type": "integer", "description": "Target height, in pixels. Optional."},
            "scale": {"type": "number", "description": "Target scale factor (e.g. 0.5 for half size). Optional."},
            "keep_aspect_ratio": {
                "type": "boolean",
                "description": "Whether to preserve the original aspect ratio when only one of width/height is given (default true).",
            },
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path"],
    },
}

VISION_ROTATE_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically rotates a local image by an arbitrary angle and writes the result. Never calls a model.",
    "use_when": "the user wants an image actually rotated (as opposed to merely detecting its rotation -- use `vision_detect_rotation` for that).",
    "avoid_when": "the user only wants to know if an image is rotated (use `vision_detect_rotation`).",
    "requires": "the image path and the rotation angle in degrees; ask the user for whichever is missing.",
    "result_semantics": "Returns the written output_path and the resulting dimensions.",
    "failure_semantics": "If the image cannot be read or the result cannot be written, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "degrees": {"type": "number", "description": "Rotation angle in degrees, counter-clockwise."},
            "expand": {"type": "boolean", "description": "Whether to expand the canvas so nothing is cropped (default true)."},
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path", "degrees"],
    },
}

VISION_FLIP_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically mirrors a local image horizontally or vertically and writes the result. Never calls a model.",
    "use_when": "the user wants an image mirrored/flipped.",
    "avoid_when": "the user wants a rotation instead (use `vision_rotate_image`).",
    "requires": "the image path and the flip direction; ask the user for whichever is missing.",
    "result_semantics": "Returns the written output_path.",
    "failure_semantics": "If the image cannot be read or the result cannot be written, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "direction": {
                "type": "string",
                "enum": ["horizontal", "vertical"],
                "description": "Flip direction.",
            },
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path", "direction"],
    },
}

VISION_ENHANCE_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically enhances a local image (auto-contrast, "
        "sharpen, optional denoise) and writes the result; optionally "
        "also asks a Vision model for further enhancement suggestions "
        "when an instruction is given."
    ),
    "use_when": "the user wants an image visually improved (sharper, better contrast).",
    "avoid_when": "the user wants the background removed instead (use `vision_remove_background`).",
    "requires": "the image path; ask the user for it if not already known.",
    "result_semantics": "Returns the written output_path, and any model-suggested notes if requested.",
    "failure_semantics": "If the image cannot be read or the result cannot be written, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "autocontrast": {"type": "boolean", "description": "Apply auto-contrast stretch (default true)."},
            "sharpen": {"type": "boolean", "description": "Apply a mild unsharp mask (default true)."},
            "denoise": {"type": "boolean", "description": "Apply a median-filter denoise (default false)."},
            "instruction": {
                "type": "string",
                "description": "Optional stylistic goal to additionally get Vision-model suggestions for.",
            },
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path"],
    },
}

VISION_REMOVE_BACKGROUND_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically removes a local image's background via "
        "classical GrabCut segmentation and writes a transparent-"
        "background PNG; optionally also asks a Vision model for a "
        "note when an instruction is given."
    ),
    "use_when": "the user wants an image's background removed/made transparent.",
    "avoid_when": "the user wants general enhancement instead (use `vision_enhance_image`).",
    "requires": "the image path; ask the user for it if not already known.",
    "result_semantics": "Returns the written output_path (a PNG with a transparent background).",
    "failure_semantics": (
        "If the image cannot be read, the result cannot be written, "
        "or the optional background-removal dependency is not "
        "installed, explain the problem in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "margin_ratio": {
                "type": "number",
                "description": "Fraction of each edge assumed to be background when seeding segmentation (default 0.05).",
            },
            "instruction": {
                "type": "string",
                "description": "Optional guidance to additionally get a Vision-model note for.",
            },
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path"],
    },
}

VISION_CONVERT_FORMAT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically converts a local image to a different file format (e.g. PNG to JPEG) and writes the result. Never calls a model.",
    "use_when": "the user wants an image saved in a different format.",
    "avoid_when": "the user just wants a smaller file in the same/similar format (use `vision_compress_image`).",
    "requires": "the image path and the target format; ask the user for whichever is missing.",
    "result_semantics": "Returns the written output_path and the format used.",
    "failure_semantics": "If the image cannot be read or the result cannot be written, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "target_format": {"type": "string", "description": "Target format, e.g. 'PNG', 'JPEG', 'WEBP', 'BMP'."},
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path", "target_format"],
    },
}

VISION_COMPRESS_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically re-encodes a local image at a lower quality/size and writes the result. Never calls a model.",
    "use_when": "the user wants an image's file size reduced.",
    "avoid_when": "the user wants a different format without necessarily reducing size (use `vision_convert_format`).",
    "requires": "the image path; ask the user for it if not already known.",
    "result_semantics": "Returns the written output_path plus the size before/after, in bytes.",
    "failure_semantics": "If the image cannot be read or the result cannot be written, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "quality": {"type": "integer", "description": "Lossy compression quality, 1-95 (default ~75)."},
            "target_format": {"type": "string", "description": "Format to re-encode as (default 'JPEG')."},
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path"],
    },
}
