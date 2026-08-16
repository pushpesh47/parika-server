"""
PARIKA Document Module - Format Detection

Deterministic, dependency-free format detection: extension first, then
a small magic-byte sniff as a fallback/confirmation for the formats
that have one (PDF, the ZIP-based Office Open XML formats DOCX/PPTX/
XLSX). Mirrors `parika/modules/ocr/pdf_support.py`'s own `is_pdf()`
magic-byte sniff, generalized to every format this Module supports.

Never raises - an unrecognized extension/signature resolves to `None`,
letting the caller decide how to react (e.g. `document.extract_text`
falls back to treating the content as plain text).
"""

from __future__ import annotations

_EXTENSION_TO_FORMAT: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".htm": "html",
    ".html": "html",
    ".txt": "txt",
    ".text": "txt",
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "json",
    ".xml": "xml",
}

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"

SUPPORTED_FORMATS: tuple[str, ...] = (
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "markdown",
    "html",
    "txt",
    "csv",
    "json",
    "xml",
)

TEXT_NATIVE_FORMATS: frozenset[str] = frozenset(
    {"markdown", "html", "txt", "csv", "json", "xml"}
)
"""
Formats read as plain text (via `filesystem.read(binary=False)`) --
never requiring `binary=True`/base64 decoding, unlike `pdf`/`docx`/
`pptx`/`xlsx`.
"""

BINARY_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "pptx", "xlsx"})


def detect_format_from_path(path: str) -> str | None:
    """
    Detect a document format from `path`'s extension alone -- the
    fast, dependency-free path used before any file content is read.
    """

    lowered = path.strip().lower()

    for suffix, format_name in _EXTENSION_TO_FORMAT.items():
        if lowered.endswith(suffix):
            return format_name

    return None


def detect_format_from_bytes(data: bytes) -> str | None:
    """
    Best-effort magic-byte sniff, used only to confirm/override an
    extension-based guess for the formats that have a reliable
    signature. DOCX/PPTX/XLSX all share the ZIP signature, so this
    alone cannot distinguish between them -- callers should prefer
    the extension-based guess when it is already one of those three,
    and use this function only as a fallback (e.g. a `.pdf` that is
    not really a PDF, or an unknown extension that happens to be a
    ZIP-based Office document).
    """

    if data[: len(_PDF_MAGIC)] == _PDF_MAGIC:
        return "pdf"

    if data[: len(_ZIP_MAGIC)] == _ZIP_MAGIC:
        return "zip"

    return None


def resolve_format(path: str, *, sniffed_bytes: bytes | None = None) -> str | None:
    """
    Resolve `path`'s document format: extension first; if the
    extension was unrecognized (or absent) and `sniffed_bytes` is
    given, fall back to the magic-byte sniff (a bare `"zip"` result
    without a resolvable extension cannot be disambiguated further,
    so it resolves to `None` rather than guessing).
    """

    from_extension = detect_format_from_path(path)

    if from_extension is not None:
        return from_extension

    if sniffed_bytes is not None:
        sniffed = detect_format_from_bytes(sniffed_bytes)

        if sniffed == "pdf":
            return "pdf"

    return None
