"""
PARIKA Vision Module - Tool Affordance Contracts (Phase 3)

Tool Affordance Contracts for `vision.analyze_image_quality`,
`vision.detect_blur`, `vision.detect_rotation`, and
`vision.detect_anomalies` -- split out of `module_driver.py` purely
to keep that file within the project's File Size Guidelines.
`vision.reason_about_image` reuses `describe_image`'s own inline
affordance shape directly in `module_driver.py`.
"""

from __future__ import annotations

from typing import Any, Mapping

_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the image.",
}
_EXPLAIN_INSTRUCTION_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": (
        "Optional. When given, additionally asks a Vision model to "
        "explain the result in words; omit it to receive only the "
        "free, deterministic metrics. Never calls a model."
    ),
}

VISION_ANALYZE_IMAGE_QUALITY_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically assesses a local image's technical "
        "quality (resolution, sharpness, contrast, brightness), never "
        "calling a model unless an explanation is explicitly asked for."
    ),
    "use_when": "the user asks whether an image is good quality, sharp, or high-resolution.",
    "avoid_when": "the user wants a content description instead (use `vision_describe_image`).",
    "requires": "the image file path; ask the user for it if not already known.",
    "result_semantics": "Returns a quality_score in [0, 1] plus the underlying metrics/warnings.",
    "failure_semantics": "If the image cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH_PARAMETER, "instruction": _EXPLAIN_INSTRUCTION_PARAMETER},
        "required": ["path"],
    },
}

VISION_DETECT_BLUR_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically measures a local image's sharpness (variance of Laplacian), never calling a model unless an explanation is asked for.",
    "use_when": "the user asks whether a photo is blurry or in focus.",
    "avoid_when": "the user wants an overall quality assessment (use `vision_analyze_image_quality`).",
    "requires": "the image file path.",
    "result_semantics": "Returns a sharpness variance and an is_blurry flag.",
    "failure_semantics": "If the image cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH_PARAMETER, "instruction": _EXPLAIN_INSTRUCTION_PARAMETER},
        "required": ["path"],
    },
}

VISION_DETECT_ROTATION_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically estimates a local image's likely rotation (0/90/180/270 degrees), never calling a model unless an explanation is asked for.",
    "use_when": "the user asks whether a photo/scan is rotated or upside down.",
    "avoid_when": "the user wants the image actually rotated (use `vision_rotate_image`).",
    "requires": "the image file path.",
    "result_semantics": (
        "Returns the estimated correction angle and a confidence "
        "margin. A low confidence means the guess is not conclusive, "
        "not necessarily wrong."
    ),
    "failure_semantics": "If the image cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH_PARAMETER, "instruction": _EXPLAIN_INSTRUCTION_PARAMETER},
        "required": ["path"],
    },
}

VISION_DETECT_ANOMALIES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically flags statistically unusual regions of a "
        "local image (local brightness outliers), never calling a "
        "model unless a semantic explanation is asked for."
    ),
    "use_when": "the user wants unusual/outlier regions of an image flagged (e.g. visual inspection, spot-checking).",
    "avoid_when": "the user wants semantic anomaly reasoning (e.g. \"is something out of place\") -- supply `instruction` to get that from a Vision model on top of the statistical result.",
    "requires": "the image file path.",
    "result_semantics": "Returns whether any anomalous regions were found, an anomaly score, and their bounding boxes.",
    "failure_semantics": "If the image cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": {
                "type": "string",
                "description": (
                    "Optional. When given, additionally asks a "
                    "Vision model to semantically explain what looks "
                    "unusual; omit it to receive only the free, "
                    "statistical result."
                ),
            },
        },
        "required": ["path"],
    },
}
