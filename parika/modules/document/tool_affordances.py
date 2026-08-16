"""
PARIKA Document Module - Tool Affordance Contracts

Every `document.*` TOOL Capability's Tool Affordance Contract (see
`docs/architecture/Request_Understanding.md` §4.4), as plain data --
read generically by `ai_context.tool_context.discover_tool_specs()`;
AI Context Engineering never defines or duplicates this content, only
ever reads it back from each Capability's own
`metadata["tool_affordance"]`. Mirrors exactly
`parika/modules/ocr/tool_affordances.py`'s own shape, generated with
small helper functions here purely to avoid ~30 near-identical literal
dicts (the 10 `document.read_*` Capabilities differ only by format
name/extension).
"""

from __future__ import annotations

from typing import Any, Mapping

_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the document.",
}
_OPTIONAL_INSTRUCTION_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "What to focus on. Optional; defaults to a general result for this capability.",
}
_OTHER_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the second document to compare against.",
}

_FORMAT_LABELS: Mapping[str, str] = {
    "pdf": "PDF",
    "docx": "Word (DOCX)",
    "pptx": "PowerPoint (PPTX)",
    "xlsx": "Excel (XLSX)",
    "markdown": "Markdown",
    "html": "HTML",
    "txt": "plain text",
    "csv": "CSV",
    "json": "JSON",
    "xml": "XML",
}


def _read_affordance(document_format: str) -> Mapping[str, Any]:
    label = _FORMAT_LABELS[document_format]

    return {
        "purpose": f"Reads a local {label} file and returns its extracted text/structure.",
        "use_when": f"the user wants to read, open, or extract content from a {label} file.",
        "avoid_when": (
            f"the file is not really a {label} file - use document_extract_text "
            "instead, which auto-detects the format."
        ),
        "requires": "the document file path; ask the user for it if not already known.",
        "result_semantics": (
            "Returns the document's extracted text plus, when available for "
            "this format, its metadata/headings/tables/links/images. Present "
            "it directly, formatted the way the user asked for it, rather "
            "than as raw tool output."
        ),
        "failure_semantics": (
            "If the file cannot be read, is not a valid "
            f"{label} file, or a required optional dependency is not "
            "installed, explain the problem in plain language without "
            "exposing internal exception details."
        ),
        "parameters": {
            "type": "object",
            "properties": {"path": _PATH_PARAMETER},
            "required": ["path"],
        },
    }


DOCUMENT_EXTRACT_TEXT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "The universal entry point for reading a local document file of "
        "any supported format (PDF, DOCX, PPTX, XLSX, Markdown, HTML, TXT, "
        "CSV, JSON, XML): auto-detects the format and returns its extracted "
        "text, using OCR internally only when a PDF has no usable native "
        "text layer."
    ),
    "use_when": (
        "the user wants a document's text or content and you do not need "
        "one specific format's own structured Tool (tables/images/links/"
        "headings/metadata)."
    ),
    "avoid_when": (
        "the user wants a specific structured facet instead (metadata, "
        "tables, images, links, headings, sections) - use the matching "
        "document_extract_* Tool instead. Also avoid for a plain image "
        "file (jpg/png/...) with no document format - use OCR's/Vision's "
        "own Tools for that."
    ),
    "requires": "the document file path; ask the user for it if not already known.",
    "result_semantics": (
        "Returns the extracted text (for a PDF, also a per-page 'pages' "
        "breakdown) plus best-effort metadata/headings/tables/links. "
        "Present it directly, formatted the way the user asked for it, "
        "rather than as raw tool output."
    ),
    "failure_semantics": (
        "If the file cannot be read, its format could not be determined, "
        "or a required optional dependency is not installed, explain the "
        "problem in plain language without exposing internal exception "
        "details."
    ),
    "parameters": {
        "type": "object",
        "properties": {"path": _PATH_PARAMETER},
        "required": ["path"],
    },
}

READ_TOOL_AFFORDANCES: Mapping[str, Mapping[str, Any]] = {
    document_format: _read_affordance(document_format)
    for document_format in _FORMAT_LABELS
    if document_format != "pdf"
} | {"pdf": _read_affordance("pdf")}


def _extraction_affordance(
    facet_label: str, use_when: str, result_semantics: str
) -> Mapping[str, Any]:
    return {
        "purpose": f"Extracts a local document's {facet_label} without its full text.",
        "use_when": use_when,
        "avoid_when": (
            "the user wants the document's full text or a different "
            "structured facet instead - use document_extract_text or the "
            "matching document_extract_* Tool."
        ),
        "requires": "the document file path; ask the user for it if not already known.",
        "result_semantics": result_semantics,
        "failure_semantics": (
            "If the file cannot be read, its format could not be "
            "determined, or a required optional dependency is not "
            "installed, explain the problem in plain language without "
            "exposing internal exception details."
        ),
        "parameters": {
            "type": "object",
            "properties": {"path": _PATH_PARAMETER},
            "required": ["path"],
        },
    }


EXTRACT_METADATA_TOOL_AFFORDANCE = _extraction_affordance(
    "metadata (title, author, dates, page count, word count, language)",
    "the user asks about a document's title, author, creation/modification date, page count, or similar metadata.",
    "Returns the document's metadata fields. Present the relevant fields directly, in plain language.",
)
EXTRACT_IMAGES_TOOL_AFFORDANCE = _extraction_affordance(
    "embedded images (identity, format, page/slide location)",
    "the user asks how many images a document contains, or where they appear.",
    "Returns each embedded image's index, content type, and page/slide, when known. This never returns image pixel data.",
)
EXTRACT_TABLES_TOOL_AFFORDANCE = _extraction_affordance(
    "tables (rows and columns)",
    "the user wants a document's tables as structured rows/columns rather than raw text.",
    "Returns each table's headers and rows. Present them clearly, never as raw JSON, unless the user specifically asked for JSON.",
)
EXTRACT_LINKS_TOOL_AFFORDANCE = _extraction_affordance(
    "hyperlinks",
    "the user wants a document's links/URLs listed.",
    "Returns each link's visible text and target URL.",
)
EXTRACT_HEADINGS_TOOL_AFFORDANCE = _extraction_affordance(
    "headings (outline/table of contents)",
    "the user wants a document's outline, table of contents, or heading structure.",
    "Returns each heading's level and text, in document order.",
)
EXTRACT_SECTIONS_TOOL_AFFORDANCE = _extraction_affordance(
    "sections (the text under each heading)",
    "the user wants a document broken down by section rather than as one flat block of text.",
    "Returns each section's heading (or null for un-headed leading content) and its text.",
)
EXTRACT_REFERENCES_TOOL_AFFORDANCE = _extraction_affordance(
    "bibliography/citation references",
    "the user wants a document's references, citations, or bibliography listed.",
    "Returns each detected reference entry as plain text, in document order. This is a best-effort heuristic, not guaranteed complete.",
)
EXTRACT_ATTACHMENTS_TOOL_AFFORDANCE = _extraction_affordance(
    "embedded attachments/objects",
    "the user asks whether a document (DOCX/PPTX/XLSX) has embedded files or objects.",
    "Returns each embedded attachment's name, package path, and size in bytes. Formats with no such notion return an empty list.",
)


def _analysis_affordance(
    purpose: str,
    use_when: str,
    result_semantics: str,
    *,
    extra_properties: Mapping[str, Any] | None = None,
    required: tuple[str, ...] = ("path",),
) -> Mapping[str, Any]:
    properties: dict[str, Any] = {"path": _PATH_PARAMETER}

    if extra_properties:
        properties.update(extra_properties)

    return {
        "purpose": purpose,
        "use_when": use_when,
        "avoid_when": "a simpler, deterministic Tool already answers the question (e.g. document_extract_metadata for basic facts).",
        "requires": "the document file path; ask the user for it if not already known.",
        "result_semantics": result_semantics,
        "failure_semantics": (
            "If the file cannot be read or no suitable model is currently "
            "available, explain the problem in plain language without "
            "exposing internal exception details."
        ),
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


SUMMARIZE_TOOL_AFFORDANCE = _analysis_affordance(
    "Summarizes a local document's content.",
    "the user wants a summary, TL;DR, or overview of a document.",
    "Returns the summary in prose. Present it directly.",
    extra_properties={"instruction": _OPTIONAL_INSTRUCTION_PARAMETER},
)
ANSWER_QUESTION_TOOL_AFFORDANCE = _analysis_affordance(
    "Answers a specific question about a local document's content.",
    "the user asks a specific question about a document rather than wanting its full text or a summary.",
    "Returns the answer, grounded in the document's content. Present it directly.",
    extra_properties={
        "question": {"type": "string", "description": "The specific question to answer about the document."}
    },
    required=("path", "question"),
)
COMPARE_DOCUMENTS_TOOL_AFFORDANCE = _analysis_affordance(
    "Compares two local documents and explains their similarities/differences.",
    "the user wants to know how two documents differ or agree.",
    "Returns a prose comparison. Present it directly.",
    extra_properties={"other_path": _OTHER_PATH_PARAMETER},
    required=("path", "other_path"),
)
SEARCH_TOOL_AFFORDANCE = _analysis_affordance(
    "Searches a local document's extracted text for a literal string or regular expression.",
    "the user wants to find where a specific term or pattern appears in a document.",
    "Returns each match's location and surrounding context. Present the matches directly.",
    extra_properties={
        "query": {"type": "string", "description": "The text or regular expression to search for."},
        "regex": {"type": "boolean", "description": "Whether 'query' is a regular expression. Optional; defaults to false."},
        "case_sensitive": {"type": "boolean", "description": "Whether the search is case-sensitive. Optional; defaults to false."},
    },
    required=("path", "query"),
)
CLASSIFY_TOOL_AFFORDANCE = _analysis_affordance(
    "Classifies a local document's topic/category based on its content.",
    "the user wants to know what category or topic a document belongs to.",
    "Returns the classification with a brief rationale. Present it directly.",
    extra_properties={"instruction": _OPTIONAL_INSTRUCTION_PARAMETER},
)
DETECT_LANGUAGE_TOOL_AFFORDANCE = _analysis_affordance(
    "Detects the dominant language of a local document's text.",
    "the user asks what language a document is written in.",
    "Returns the most likely language code and confidence, plus runner-up candidates.",
)
DETECT_DOCUMENT_TYPE_TOOL_AFFORDANCE = _analysis_affordance(
    "Infers a local document's real-world type (e.g. invoice, resume, contract, report) from its content.",
    "the user asks what kind of document a file is.",
    "Returns the inferred document type with a brief rationale. Present it directly.",
)
EXTRACT_ENTITIES_TOOL_AFFORDANCE = _analysis_affordance(
    "Extracts named entities (people, organizations, locations, products, ...) mentioned in a local document.",
    "the user wants the people, organizations, or places mentioned in a document listed.",
    "Returns the entities found, grouped by type. Present them clearly.",
)
EXTRACT_KEYWORDS_TOOL_AFFORDANCE = _analysis_affordance(
    "Extracts a local document's most frequent, meaningful terms.",
    "the user wants a document's key terms or topics listed.",
    "Returns ranked keywords with their frequency. Present them clearly, never as raw JSON.",
)
EXTRACT_ACTION_ITEMS_TOOL_AFFORDANCE = _analysis_affordance(
    "Extracts action items, tasks, or follow-ups mentioned in a local document.",
    "the user wants the to-dos or action items in a document (e.g. meeting notes) listed.",
    "Returns each action item in prose or as a list. Present it directly.",
)
EXTRACT_DATES_TOOL_AFFORDANCE = _analysis_affordance(
    "Extracts date mentions found in a local document's text.",
    "the user wants every date mentioned in a document listed.",
    "Returns the distinct date strings found, in first-seen order. This is a best-effort heuristic, not guaranteed complete.",
)
EXTRACT_CONTACTS_TOOL_AFFORDANCE = _analysis_affordance(
    "Extracts contact details (email addresses, URLs, phone numbers) found in a local document's text.",
    "the user wants the contact information in a document listed.",
    "Returns the emails/URLs/phone numbers found. This is a best-effort heuristic, not guaranteed complete.",
)
EXTRACT_TIMELINE_TOOL_AFFORDANCE = _analysis_affordance(
    "Builds a chronological timeline of events described in a local document.",
    "the user wants a document's events ordered chronologically.",
    "Returns the timeline in prose or as an ordered list. Present it directly.",
)
TRANSLATE_TOOL_AFFORDANCE = _analysis_affordance(
    "Translates a local document's text into another language.",
    "the user wants a document translated.",
    "Returns the translated text. Present it directly.",
    extra_properties={
        "target_language": {"type": "string", "description": "The language to translate the document into (e.g. 'French', 'es')."}
    },
    required=("path", "target_language"),
)
DETECT_DUPLICATES_TOOL_AFFORDANCE = _analysis_affordance(
    "Deterministically checks whether two local documents are identical or near-duplicates.",
    "the user wants to know whether two documents are the same or very similar.",
    "Returns whether the documents are identical and a similarity score in [0, 1]. Present it directly.",
    extra_properties={"other_path": _OTHER_PATH_PARAMETER},
    required=("path", "other_path"),
)
