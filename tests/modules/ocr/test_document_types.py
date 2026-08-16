"""
Unit tests for the OCR Module's document-type templates and
structured-JSON parsing (`parika.modules.ocr.document_types`). Pure
and deterministic - never a Provider, never Brain/Goal.
"""

from __future__ import annotations

from parika.modules.ocr.document_types import (
    DOCUMENT_TYPE_TEMPLATES,
    parse_structured_response,
    resolve_document_type,
)


class TestResolveDocumentType:
    def test_resolves_known_type_case_insensitively(self) -> None:
        template = resolve_document_type("INVOICE")

        assert template is DOCUMENT_TYPE_TEMPLATES["invoice"]
        assert "invoice_number" in template.expected_fields

    def test_every_advertised_document_type_has_a_non_empty_instruction(self) -> None:
        for name, template in DOCUMENT_TYPE_TEMPLATES.items():
            assert template.instruction.strip(), f"{name} has an empty instruction"

    def test_none_falls_back_to_generic(self) -> None:
        assert resolve_document_type(None) is DOCUMENT_TYPE_TEMPLATES["generic"]

    def test_empty_string_falls_back_to_generic(self) -> None:
        assert resolve_document_type("") is DOCUMENT_TYPE_TEMPLATES["generic"]

    def test_unrecognized_type_falls_back_to_generic_rather_than_raising(self) -> None:
        assert (
            resolve_document_type("not_a_real_document_type")
            is DOCUMENT_TYPE_TEMPLATES["generic"]
        )


class TestParseStructuredResponse:
    def test_parses_plain_json_object(self) -> None:
        result = parse_structured_response('{"total": 42, "items": [1, 2]}')

        assert result.parsed
        assert result.data == {"total": 42, "items": [1, 2]}

    def test_parses_json_wrapped_in_markdown_fence(self) -> None:
        raw = 'Here you go:\n```json\n{"total": 42}\n```\nLet me know if you need more.'

        result = parse_structured_response(raw)

        assert result.parsed
        assert result.data == {"total": 42}

    def test_parses_json_embedded_in_prose(self) -> None:
        raw = 'The extracted fields are: {"name": "Ada", "role": "engineer"}. Done.'

        result = parse_structured_response(raw)

        assert result.parsed
        assert result.data == {"name": "Ada", "role": "engineer"}

    def test_unparseable_response_reports_parsed_false_without_raising(self) -> None:
        raw = "I could not find any structured fields in this image."

        result = parse_structured_response(raw)

        assert not result.parsed
        assert result.data is None
        assert result.raw_text == raw

    def test_parses_a_json_array(self) -> None:
        result = parse_structured_response("[1, 2, 3]")

        assert result.parsed
        assert result.data == [1, 2, 3]
