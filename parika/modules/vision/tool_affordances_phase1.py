"""
PARIKA Vision Module - Tool Affordance Contracts (Phase 1)

Tool Affordance Contracts for `vision.compare_images`,
`vision.detect_differences`, `vision.count_objects`, and
`vision.classify_image` -- split out of `module_driver.py` purely to
keep that file within the project's File Size Guidelines, exactly
like `parika/modules/ocr/tool_affordances.py`.
"""

from __future__ import annotations

from typing import Any, Mapping

_PATH_A_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the first image.",
}
_PATH_B_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the second image.",
}
_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the image.",
}
_EXPLAIN_INSTRUCTION_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": (
        "Optional. When given, additionally asks a Vision model to "
        "explain the result in words; omit it to receive only the "
        "free, deterministic metrics."
    ),
}

VISION_COMPARE_IMAGES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically measures how similar two local images are "
        "(perceptual-hash, pixel, and histogram similarity), never "
        "calling a model unless an explanation is explicitly asked for."
    ),
    "use_when": (
        "the user asks whether two images are the same/similar, or "
        "wants a similarity score between them."
    ),
    "avoid_when": (
        "the user wants the specific differing regions located (use "
        "`vision_detect_differences`), or a description of just one "
        "image (use `vision_describe_image`)."
    ),
    "requires": "both image file paths; ask the user for either if not already known.",
    "result_semantics": (
        "Returns similarity scores in [0, 1] (1.0 = identical). "
        "Present the overall_similarity plainly; mention the other "
        "sub-scores only if relevant."
    ),
    "failure_semantics": (
        "If either image cannot be read, explain the problem in "
        "plain language without exposing internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path_a": _PATH_A_PARAMETER,
            "path_b": _PATH_B_PARAMETER,
            "instruction": _EXPLAIN_INSTRUCTION_PARAMETER,
        },
        "required": ["path_a", "path_b"],
    },
}

VISION_DETECT_DIFFERENCES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically locates the pixel regions where two local "
        "images differ, never calling a model unless an explanation "
        "is explicitly asked for."
    ),
    "use_when": (
        "the user wants to know *where* or *how much* two images "
        "differ (e.g. spot-the-difference, before/after comparisons, "
        "visual regression checks)."
    ),
    "avoid_when": (
        "the user only wants an overall similarity score (use "
        "`vision_compare_images`)."
    ),
    "requires": "both image file paths; ask the user for either if not already known.",
    "result_semantics": (
        "Returns a difference_ratio in [0, 1] and the differing "
        "regions' bounding boxes. Present the overall proportion "
        "plainly and mention notable regions."
    ),
    "failure_semantics": (
        "If either image cannot be read, explain the problem in "
        "plain language without exposing internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path_a": _PATH_A_PARAMETER,
            "path_b": _PATH_B_PARAMETER,
            "instruction": _EXPLAIN_INSTRUCTION_PARAMETER,
        },
        "required": ["path_a", "path_b"],
    },
}

VISION_COUNT_OBJECTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Counts objects in a local image, preferring a free, "
        "deterministic blob count for simple scenes and falling back "
        "to a Vision model when a specific kind of object is named or "
        "the scene is too cluttered for the deterministic count to "
        "be trustworthy."
    ),
    "use_when": (
        "the user wants a numeric count of objects in an image (e.g. "
        "\"how many are there\", \"count the items\")."
    ),
    "avoid_when": (
        "the user wants objects listed/located rather than counted "
        "(use `vision_detect_objects`)."
    ),
    "requires": (
        "the image file path; ask the user for it if not already "
        "known. Optionally, which specific object to count."
    ),
    "result_semantics": (
        "Returns the count (and which method produced it). Present "
        "the number directly."
    ),
    "failure_semantics": (
        "If the image cannot be read or no Vision-capable model is "
        "available when one is needed, explain the problem in plain "
        "language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": {
                "type": "string",
                "description": (
                    "Which specific object to count. Optional; "
                    "omitting it lets the deterministic blob counter "
                    "run when the scene looks simple enough."
                ),
            },
        },
        "required": ["path"],
    },
}

VISION_CLASSIFY_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Classifies a local image, preferring a free, deterministic "
        "coarse image-type heuristic (screenshot/document/graphic/"
        "photograph) and falling back to a Vision model whenever the "
        "caller supplies specific candidate labels to classify "
        "against."
    ),
    "use_when": (
        "the user wants to know what kind of image this is, or which "
        "of several named categories it best matches."
    ),
    "avoid_when": (
        "the user wants a free-form description instead (use "
        "`vision_describe_image`)."
    ),
    "requires": "the image file path; ask the user for it if not already known.",
    "result_semantics": (
        "Returns the best-matching label with a confidence. Present "
        "it directly."
    ),
    "failure_semantics": (
        "If the image cannot be read or no Vision-capable model is "
        "available when candidate labels are supplied, explain the "
        "problem in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of candidate category labels to "
                    "classify the image against (e.g. [\"cat\", "
                    "\"dog\", \"bird\"]). Omitting it returns only "
                    "the free, deterministic coarse image-type guess."
                ),
            },
        },
        "required": ["path"],
    },
}
