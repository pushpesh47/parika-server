"""
Unit tests for the SearchQuery and SearchResult value objects.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from uuid import uuid4

import pytest

from parika.core.knowledge_manager.exceptions import (
    InvalidSearchQueryError,
    InvalidSearchResultError,
)
from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.search_result import SearchResult


def make_knowledge(**overrides: object) -> Knowledge:
    """
    Build a valid Knowledge unit, allowing individual fields to be
    overridden per test.
    """

    defaults: dict[str, object] = {
        "id": uuid4(),
        "source_id": uuid4(),
        "title": "KnowledgeManager class",
        "content": "Coordinates knowledge source lifecycle.",
        "location": "knowledge_manager.py:45",
    }
    defaults.update(overrides)

    return Knowledge(**defaults)  # type: ignore[arg-type]


def make_query(**overrides: object) -> SearchQuery:
    """
    Build a valid SearchQuery, allowing individual fields to be
    overridden per test.
    """

    defaults: dict[str, object] = {"text": "how does indexing work"}
    defaults.update(overrides)

    return SearchQuery(**defaults)  # type: ignore[arg-type]


def make_result(**overrides: object) -> SearchResult:
    """
    Build a valid SearchResult, allowing individual fields to be
    overridden per test.
    """

    defaults: dict[str, object] = {
        "knowledge": make_knowledge(),
        "score": 0.5,
    }
    defaults.update(overrides)

    return SearchResult(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# SearchQuery validation and normalization
# ---------------------------------------------------------------------


class TestSearchQuery:
    def test_strips_text(self) -> None:
        query = make_query(text="  hello world  ")

        assert query.text == "hello world"

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(InvalidSearchQueryError):
            make_query(text="   ")

    def test_rejects_zero_limit(self) -> None:
        with pytest.raises(InvalidSearchQueryError):
            make_query(limit=0)

    def test_rejects_negative_limit(self) -> None:
        with pytest.raises(InvalidSearchQueryError):
            make_query(limit=-1)

    def test_rejects_negative_offset(self) -> None:
        with pytest.raises(InvalidSearchQueryError):
            make_query(offset=-1)

    def test_defaults(self) -> None:
        query = make_query()

        assert query.source_ids == frozenset()
        assert query.limit == 20
        assert query.offset == 0
        assert query.include_disabled is False
        assert dict(query.metadata_filters) == {}

    def test_source_ids_normalized_to_frozenset(self) -> None:
        source_id = uuid4()
        query = make_query(source_ids=[source_id, source_id])

        assert query.source_ids == frozenset({source_id})

    def test_metadata_filters_normalized_to_mapping_proxy(self) -> None:
        query = make_query(metadata_filters={"language": "python"})

        assert isinstance(query.metadata_filters, MappingProxyType)
        assert query.metadata_filters["language"] == "python"

    def test_instance_is_frozen(self) -> None:
        query = make_query()

        with pytest.raises(FrozenInstanceError):
            query.text = "renamed"  # type: ignore[misc]


# ---------------------------------------------------------------------
# SearchResult validation and normalization
# ---------------------------------------------------------------------


class TestSearchResult:
    def test_rejects_negative_score(self) -> None:
        with pytest.raises(InvalidSearchResultError):
            make_result(score=-0.1)

    def test_accepts_zero_score(self) -> None:
        result = make_result(score=0.0)

        assert result.score == 0.0

    def test_metadata_normalized_to_mapping_proxy(self) -> None:
        result = make_result(metadata={"engine": "fake"})

        assert isinstance(result.metadata, MappingProxyType)
        assert result.metadata["engine"] == "fake"

    def test_instance_is_frozen(self) -> None:
        result = make_result()

        with pytest.raises(FrozenInstanceError):
            result.score = 1.0  # type: ignore[misc]
