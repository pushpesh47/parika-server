"""
PARIKA Vision Module - Tool Affordance Contracts (Phase 2)

Tool Affordance Contracts for `vision.detect_faces`,
`vision.detect_qr_codes`, and `vision.detect_barcodes` -- split out
of `module_driver.py` purely to keep that file within the project's
File Size Guidelines. `vision.detect_logos` reuses `describe_image`'s
own inline affordance shape directly in `module_driver.py` (it is a
plain `VisionToolDriver`/`VisionToolSpec` entry, not one of these
deterministic-first drivers).
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
        "narrate the result in words; omit it to receive only the "
        "free, deterministic detections."
    ),
}

VISION_DETECT_FACES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically detects human faces in a local image "
        "(bounding boxes and count) via a classical face detector, "
        "never calling a model unless a narration is explicitly "
        "asked for."
    ),
    "use_when": (
        "the user asks how many people/faces are in an image, or "
        "where they are."
    ),
    "avoid_when": (
        "the user wants faces identified (who someone is) or "
        "described -- this only locates/counts faces, it never "
        "recognizes or describes people."
    ),
    "requires": "the image file path; ask the user for it if not already known.",
    "result_semantics": "Returns the face count and bounding boxes. Present the count directly.",
    "failure_semantics": (
        "If the image cannot be read, or the optional face-detection "
        "dependency is not installed, explain the problem in plain "
        "language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": _EXPLAIN_INSTRUCTION_PARAMETER,
        },
        "required": ["path"],
    },
}

VISION_DETECT_QR_CODES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically decodes every QR code in a local image "
        "via a real barcode-decoding library, never a model."
    ),
    "use_when": "the user wants to read a QR code's content from an image.",
    "avoid_when": "the code is a 1D/other 2D barcode, not a QR code (use `vision_detect_barcodes`).",
    "requires": "the image file path; ask the user for it if not already known.",
    "result_semantics": "Returns each decoded QR code's data. Present it directly.",
    "failure_semantics": (
        "If the image cannot be read, no QR code is found, or the "
        "optional decoding dependency is not installed, explain the "
        "problem in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": _EXPLAIN_INSTRUCTION_PARAMETER,
        },
        "required": ["path"],
    },
}

VISION_DETECT_BARCODES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Deterministically decodes every 1D/2D barcode (EAN, UPC, "
        "Code128, ...; excluding QR codes) in a local image via a "
        "real barcode-decoding library, never a model."
    ),
    "use_when": "the user wants to read a barcode's content from an image (e.g. a product barcode).",
    "avoid_when": "the code is a QR code (use `vision_detect_qr_codes`).",
    "requires": "the image file path; ask the user for it if not already known.",
    "result_semantics": "Returns each decoded barcode's data and symbology. Present it directly.",
    "failure_semantics": (
        "If the image cannot be read, no barcode is found, or the "
        "optional decoding dependency is not installed, explain the "
        "problem in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": _EXPLAIN_INSTRUCTION_PARAMETER,
        },
        "required": ["path"],
    },
}
