from __future__ import annotations

from parika.modules.document import text_analysis


class TestExtractKeywords:
    def test_ranks_by_frequency_excluding_stopwords(self) -> None:
        text = "apple apple apple banana banana the a of"
        keywords = text_analysis.extract_keywords(text, max_keywords=2)

        assert keywords[0] == {"keyword": "apple", "count": 3}
        assert keywords[1] == {"keyword": "banana", "count": 2}


class TestExtractDates:
    def test_finds_multiple_date_formats(self) -> None:
        text = "Signed on 2024-01-05, due 01/05/2024, renewed 5 January 2025."
        dates = text_analysis.extract_dates(text)

        assert "2024-01-05" in dates
        assert "01/05/2024" in dates
        assert any("January 2025" in d for d in dates)

    def test_no_dates_returns_empty_list(self) -> None:
        assert text_analysis.extract_dates("no dates here at all") == []


class TestExtractContacts:
    def test_finds_emails_urls_and_phone_numbers(self) -> None:
        text = (
            "Contact ada@example.com or visit https://example.com/info. "
            "Call +1 415-555-0134 for support."
        )
        contacts = text_analysis.extract_contacts(text)

        assert contacts["emails"] == ["ada@example.com"]
        assert contacts["urls"] == ["https://example.com/info"]
        assert contacts["phone_numbers"]


class TestExtractReferences:
    def test_extracts_numbered_entries_after_references_heading(self) -> None:
        text = (
            "Body text here.\n\n"
            "References\n"
            "[1] Smith, J. (2020). A Paper. Journal.\n"
            "[2] Doe, A. (2021). Another Paper. Journal.\n"
        )
        references = text_analysis.extract_references(text)

        assert len(references) == 2
        assert references[0].startswith("[1]")

    def test_falls_back_to_doi_scan_when_no_numbered_entries(self) -> None:
        text = "See doi:10.1234/example.5678 for details."
        references = text_analysis.extract_references(text)

        assert references == ["DOI: 10.1234/example.5678"]


class TestSearchText:
    def test_finds_case_insensitive_substring_with_context(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        matches = text_analysis.search_text(text, "FOX")

        assert len(matches) == 1
        assert "fox" in matches[0].context.lower()

    def test_regex_search(self) -> None:
        text = "order-1 order-2 order-3"
        matches = text_analysis.search_text(text, r"order-\d", use_regex=True)

        assert len(matches) == 3

    def test_empty_query_returns_no_matches(self) -> None:
        assert text_analysis.search_text("some text", "") == []


class TestDetectLanguage:
    def test_empty_text_is_not_detected(self) -> None:
        result = text_analysis.detect_language("   ")
        assert result.detected is False


class TestDuplicateDetection:
    def test_identical_normalized_text_is_identical(self) -> None:
        result = text_analysis.detect_duplicates_pair(
            "Hello   World", "hello world"
        )
        assert result.identical is True
        assert result.similarity == 1.0

    def test_disjoint_text_has_low_similarity(self) -> None:
        result = text_analysis.detect_duplicates_pair(
            "apple banana cherry", "dog cat fish"
        )
        assert result.identical is False
        assert result.similarity == 0.0

    def test_partial_overlap_has_partial_similarity(self) -> None:
        result = text_analysis.detect_duplicates_pair(
            "apple banana cherry date", "apple banana fig grape"
        )
        assert result.identical is False
        assert 0.0 < result.similarity < 1.0
