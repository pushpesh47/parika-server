"""
PARIKA OCR Module - Document-Type Templates & Structured Parsing

Two small, deliberately data-driven pieces shared by
`structured_driver.py`'s `ocr.extract_table`, `ocr.extract_form`, and
`document.extract_text`:

1. `DOCUMENT_TYPE_TEMPLATES` - a plain table mapping a `document_type`
   string (invoice, receipt, resume, passport, id_card,
   driving_license, business_card, bank_statement, utility_bill,
   generic) to a pre-authored recognition instruction and its
   expected field names. This single, generic, table-driven
   `document.extract_text` Capability replaces what would otherwise be
   nine separate, near-duplicate document-type Capabilities/Tools -
   the same instruction-parameterization `ocr.extract_text` already
   uses, just pre-authored per type rather than left to the caller.
   Add a new document type by adding one entry here; no driver or
   Capability code needs to change.
2. `parse_structured_response()` - a deterministic, best-effort JSON
   extractor for a Provider model's raw text response (some models
   wrap JSON in a Markdown code fence, or add a short preface/
   postscript around it). Never raises: a response that cannot be
   parsed as JSON at all is reported as `parsed=False` with the raw
   text preserved, so the caller/model still sees the model's actual
   answer rather than a hard failure - recognition succeeded, only
   its formatting did not.

Both are pure and deterministic, with no Brain/Goal/Provider concept
of their own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentTypeTemplate:
    """One document type's recognition instruction and expected fields."""

    instruction: str
    expected_fields: tuple[str, ...]


def _template(instruction: str, *fields: str) -> DocumentTypeTemplate:
    return DocumentTypeTemplate(instruction=instruction, expected_fields=fields)


DOCUMENT_TYPE_TEMPLATES: Mapping[str, DocumentTypeTemplate] = {
    "invoice": _template(
        "Extract this invoice's fields as strict JSON with keys: "
        "invoice_number, invoice_date, due_date, vendor_name, "
        "customer_name, line_items (array of {description, quantity, "
        "unit_price, amount}), subtotal, tax, total. Use null for any "
        "field you cannot find. Respond with JSON only.",
        "invoice_number", "invoice_date", "due_date", "vendor_name",
        "customer_name", "line_items", "subtotal", "tax", "total",
    ),
    "receipt": _template(
        "Extract this receipt's fields as strict JSON with keys: "
        "merchant_name, date, time, items (array of {description, "
        "quantity, price}), subtotal, tax, total, payment_method. Use "
        "null for any field you cannot find. Respond with JSON only.",
        "merchant_name", "date", "time", "items", "subtotal", "tax",
        "total", "payment_method",
    ),
    "resume": _template(
        "Extract this resume's fields as strict JSON with keys: "
        "full_name, email, phone, summary, skills (array of strings), "
        "work_experience (array of {title, company, start_date, "
        "end_date, description}), education (array of {degree, "
        "institution, year}). Use null/[] for any field you cannot "
        "find. Respond with JSON only.",
        "full_name", "email", "phone", "summary", "skills",
        "work_experience", "education",
    ),
    "passport": _template(
        "Extract this passport's fields as strict JSON with keys: "
        "passport_number, surname, given_names, nationality, "
        "date_of_birth, sex, place_of_birth, date_of_issue, "
        "date_of_expiry, issuing_authority. Use null for any field "
        "you cannot find. Respond with JSON only.",
        "passport_number", "surname", "given_names", "nationality",
        "date_of_birth", "sex", "place_of_birth", "date_of_issue",
        "date_of_expiry", "issuing_authority",
    ),
    "id_card": _template(
        "Extract this identity card's fields as strict JSON with "
        "keys: id_number, full_name, date_of_birth, address, sex, "
        "date_of_issue, date_of_expiry, issuing_authority. Use null "
        "for any field you cannot find. Respond with JSON only.",
        "id_number", "full_name", "date_of_birth", "address", "sex",
        "date_of_issue", "date_of_expiry", "issuing_authority",
    ),
    "driving_license": _template(
        "Extract this driving license's fields as strict JSON with "
        "keys: license_number, full_name, date_of_birth, address, "
        "vehicle_classes, date_of_issue, date_of_expiry, "
        "issuing_authority. Use null for any field you cannot find. "
        "Respond with JSON only.",
        "license_number", "full_name", "date_of_birth", "address",
        "vehicle_classes", "date_of_issue", "date_of_expiry",
        "issuing_authority",
    ),
    "business_card": _template(
        "Extract this business card's fields as strict JSON with "
        "keys: full_name, job_title, company, email, phone, website, "
        "address. Use null for any field you cannot find. Respond "
        "with JSON only.",
        "full_name", "job_title", "company", "email", "phone",
        "website", "address",
    ),
    "bank_statement": _template(
        "Extract this bank statement's fields as strict JSON with "
        "keys: account_holder, account_number, statement_period, "
        "opening_balance, closing_balance, transactions (array of "
        "{date, description, amount, balance}). Use null/[] for any "
        "field you cannot find. Respond with JSON only.",
        "account_holder", "account_number", "statement_period",
        "opening_balance", "closing_balance", "transactions",
    ),
    "utility_bill": _template(
        "Extract this utility bill's fields as strict JSON with "
        "keys: provider_name, account_number, billing_period, "
        "amount_due, due_date, service_address. Use null for any "
        "field you cannot find. Respond with JSON only.",
        "provider_name", "account_number", "billing_period",
        "amount_due", "due_date", "service_address",
    ),
    "generic": _template(
        "Extract every clearly labeled field (label/value pair) "
        "visible in this document as strict JSON: an object mapping "
        "each label to its value. Respond with JSON only.",
    ),
}
"""
Data-driven document-type -> instruction/expected-fields table -
see this module's own docstring.
"""


DEFAULT_DOCUMENT_TYPE = "generic"


def resolve_document_type(document_type: str | None) -> DocumentTypeTemplate:
    """
    Resolve a caller-supplied `document_type` string to its template,
    case-insensitively, falling back to `"generic"` for `None`, empty,
    or unrecognized values rather than raising - an unrecognized
    document type is still worth extracting generically.
    """

    if not document_type:
        return DOCUMENT_TYPE_TEMPLATES[DEFAULT_DOCUMENT_TYPE]

    return DOCUMENT_TYPE_TEMPLATES.get(
        document_type.strip().lower(), DOCUMENT_TYPE_TEMPLATES[DEFAULT_DOCUMENT_TYPE]
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredParseResult:
    """Result of `parse_structured_response()` - see its docstring."""

    parsed: bool
    data: object | None
    raw_text: str


def parse_structured_response(raw_text: str) -> StructuredParseResult:
    """
    Best-effort, deterministic JSON extraction from a Provider model's
    raw text response. Tries, in order: (1) the whole response as
    JSON; (2) the content of a Markdown ```json fence, if present;
    (3) the widest `{...}`/`[...]` substring found. Never raises - a
    response that cannot be parsed as JSON at all is reported as
    `parsed=False` with `raw_text` preserved.
    """

    stripped = raw_text.strip()
    data = _try_json(stripped)

    if data is not None:
        return StructuredParseResult(parsed=True, data=data, raw_text=raw_text)

    fence_match = _JSON_FENCE_PATTERN.search(raw_text)

    if fence_match:
        data = _try_json(fence_match.group(1).strip())

        if data is not None:
            return StructuredParseResult(parsed=True, data=data, raw_text=raw_text)

    substring = _widest_json_substring(stripped)

    if substring is not None:
        data = _try_json(substring)

        if data is not None:
            return StructuredParseResult(parsed=True, data=data, raw_text=raw_text)

    return StructuredParseResult(parsed=False, data=None, raw_text=raw_text)


def _try_json(candidate: str) -> object | None:
    if not candidate:
        return None

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _widest_json_substring(text: str) -> str | None:
    """Return the substring spanning the first `{`/`[` to the last matching `}`/`]`, if any."""

    open_positions = [index for index, char in enumerate(text) if char in "{["]
    close_positions = [index for index, char in enumerate(text) if char in "}]"]

    if not open_positions or not close_positions:
        return None

    start, end = open_positions[0], close_positions[-1]

    if end <= start:
        return None

    return text[start : end + 1]
