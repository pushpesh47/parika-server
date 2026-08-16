"""
PARIKA OCR Module - Tool Affordance Contracts

Every `ocr.*` TOOL Capability's Tool Affordance Contract (see
`docs/architecture/Request_Understanding.md` §4.4), as plain data -
split out of `module_driver.py` purely to keep that file within the
project's File Size Guidelines
(`docs/architecture/PARIKA_Core_Coding_Standards.md`). Read generically
by `ai_context.tool_context.discover_tool_specs()`; AI Context
Engineering never defines or duplicates this content, only ever reads
it back from each Capability's own `metadata["tool_affordance"]`.
"""

from __future__ import annotations

from typing import Any, Mapping

_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the image or PDF.",
}
_TEXT_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": (
        "Text already recognized earlier in this conversation (e.g. by "
        "ocr.extract_text). Prefer this over 'path' whenever you already "
        "have it - it costs no additional OCR call."
    ),
}
_OPTIONAL_INSTRUCTION_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Additional guidance for the recognizer. Optional.",
}

OCR_EXTRACT_TEXT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Provides OCR (optical character recognition) text extraction "
        "from an image or PDF file already stored locally."
    ),
    "use_when": (
        "the user wants to read, extract, or recognize text or "
        "specific fields from an image or PDF (e.g. a scanned "
        "document, ID card, receipt, form, or photo containing text)."
    ),
    "avoid_when": (
        "the user wants a general visual description rather than "
        "text extraction, or the text is already available from an "
        "earlier Tool result in this conversation, or the user wants "
        "a table/form's structured fields (use ocr.extract_table/"
        "ocr.extract_form/document.extract_text instead)."
    ),
    "requires": "the image or PDF file path; ask the user for it if not already known.",
    "result_semantics": (
        "Returns the recognized text (for a PDF, also a per-page "
        "'pages' breakdown). Present it directly, formatted the way "
        "the user asked for it (e.g. as specific labeled fields) "
        "rather than as raw tool output."
    ),
    "failure_semantics": (
        "If the file cannot be read or no OCR-capable model is "
        "currently available, explain the problem in plain language "
        "without exposing internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": {
                "type": "string",
                "description": (
                    "What to extract or focus on (e.g. specific field "
                    "names). Optional; defaults to extracting all "
                    "readable text."
                ),
            },
            "language": {
                "type": "string",
                "description": "A language to focus recognition on. Optional.",
            },
            "region": {
                "type": "object",
                "description": (
                    "A pixel rectangle {x, y, width, height} to crop to "
                    "before recognition, for region-specific OCR. Optional."
                ),
            },
        },
        "required": ["path"],
    },
}

OCR_DETECT_ORIENTATION_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Detects an image's likely page rotation (0/90/180/270 "
        "degrees) without reading any of its text."
    ),
    "use_when": (
        "the user asks whether a scan/photo is rotated or upside "
        "down, or before deciding whether to rotate it."
    ),
    "avoid_when": (
        "the user actually wants the image's text - use "
        "ocr.extract_text instead; this never returns any text."
    ),
    "requires": "the image file path.",
    "result_semantics": (
        "Returns the estimated correction angle and a confidence "
        "margin. A low confidence means the guess is not conclusive, "
        "not necessarily wrong - mention that nuance if relevant."
    ),
    "failure_semantics": (
        "If the optional image-analysis dependency is unavailable or "
        "the image cannot be read, explain the problem in plain "
        "language."
    ),
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH_PARAMETER},
        "required": ["path"],
    },
}

OCR_DETECT_QUALITY_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Assesses a document image's likely OCR readability "
        "(resolution, sharpness, contrast) without reading any of its "
        "text."
    ),
    "use_when": (
        "the user asks whether a scan/photo is good enough quality, "
        "blurry, or too low-resolution, or before deciding whether to "
        "re-scan/re-photograph it."
    ),
    "avoid_when": (
        "the user actually wants the image's text - use "
        "ocr.extract_text instead."
    ),
    "requires": "the image file path.",
    "result_semantics": (
        "Returns a quality score in [0, 1] plus specific warnings "
        "(blurry/low-resolution/low-contrast). A low score means "
        "recognition may struggle, not that it will necessarily fail."
    ),
    "failure_semantics": (
        "If the optional image-analysis dependency is unavailable or "
        "the image cannot be read, explain the problem in plain "
        "language."
    ),
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH_PARAMETER},
        "required": ["path"],
    },
}

OCR_DETECT_LANGUAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Detects the dominant language of text - either text you "
        "already have from an earlier OCR result, or text in an image."
    ),
    "use_when": "the user asks what language a document or image is written in.",
    "avoid_when": (
        "you already extracted this image's text earlier in this "
        "conversation - pass that text directly via 'text' instead of "
        "'path', to avoid a second OCR call."
    ),
    "requires": "either 'text' (already-recognized text) or 'path' (an image to recognize first).",
    "result_semantics": (
        "Returns the most likely language code and confidence, plus "
        "runner-up candidates."
    ),
    "failure_semantics": (
        "If the optional language-detection dependency is unavailable, "
        "or neither 'text' nor 'path' was usable, explain the problem "
        "in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": _TEXT_PARAMETER,
            "path": _PATH_PARAMETER,
            "instruction": _OPTIONAL_INSTRUCTION_PARAMETER,
        },
        "required": [],
    },
}

OCR_EXTRACT_LAYOUT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Extracts text and its structural layout (lines, paragraphs, "
        "probable headings, reading order) - either from text you "
        "already have, or from an image."
    ),
    "use_when": (
        "the user wants a document's structure preserved (paragraphs/"
        "headings/reading order), not just a flat block of text."
    ),
    "avoid_when": (
        "you already extracted this image's text earlier in this "
        "conversation - pass that text directly via 'text' instead of "
        "'path'. Also avoid when the user wants a table or form's "
        "specific fields (use ocr.extract_table/ocr.extract_form "
        "instead)."
    ),
    "requires": "either 'text' (already-recognized text) or 'path' (an image to recognize first).",
    "result_semantics": (
        "Returns lines/paragraphs/headings plus counts. Heading "
        "detection is a best-effort heuristic, not guaranteed complete."
    ),
    "failure_semantics": (
        "If neither 'text' nor 'path' was usable, explain the problem "
        "in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": _TEXT_PARAMETER,
            "path": _PATH_PARAMETER,
            "instruction": _OPTIONAL_INSTRUCTION_PARAMETER,
        },
        "required": [],
    },
}

OCR_EXTRACT_TABLE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Extracts a table's rows and columns from an image as structured data.",
    "use_when": "the user wants a table's contents as rows/columns rather than raw text.",
    "avoid_when": "the image has no table - use ocr.extract_text instead.",
    "requires": "the image file path.",
    "result_semantics": (
        "Returns 'data' (the parsed table if the model's response was "
        "valid JSON; otherwise 'raw_text' with parsed=false) and, when "
        "a ruled/gridded table was found deterministically, its pixel "
        "region. Present the table clearly, never as raw JSON, unless "
        "the user specifically asked for JSON."
    ),
    "failure_semantics": (
        "If the image cannot be read or no OCR-capable model is "
        "currently available, explain the problem in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": _OPTIONAL_INSTRUCTION_PARAMETER,
        },
        "required": ["path"],
    },
}

OCR_EXTRACT_FORM_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Extracts a form's labeled fields, key-value pairs, and "
        "checkbox/radio selections from an image as structured data."
    ),
    "use_when": "the user wants a form's individual fields/values rather than raw text.",
    "avoid_when": "the image is not a form - use ocr.extract_text instead.",
    "requires": "the image file path.",
    "result_semantics": (
        "Returns 'data' (the parsed fields if the model's response "
        "was valid JSON; otherwise 'raw_text' with parsed=false). "
        "Present the fields clearly, never as raw JSON, unless the "
        "user specifically asked for JSON."
    ),
    "failure_semantics": (
        "If the image cannot be read or no OCR-capable model is "
        "currently available, explain the problem in plain language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _PATH_PARAMETER,
            "instruction": _OPTIONAL_INSTRUCTION_PARAMETER,
        },
        "required": ["path"],
    },
}


