"""
Unit tests for the KnowledgeSource and Knowledge value objects.

Both objects follow the same immutable-dataclass idiom used throughout
the KnowledgeManager component: `__post_init__` strips/validates string
fields, normalizes `metadata` into a `MappingProxyType`, and defines
identity-based `__eq__`/`__hash__`.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from uuid import uuid4

import pytest

from parika.core.knowledge_manager.exceptions import (
    InvalidKnowledgeError,
    InvalidKnowledgeSourceError,
)
from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import (
    KnowledgeSourceStatus,
)


def make_source(**overrides: object) -> KnowledgeSource:
    """
    Build a valid KnowledgeSource, allowing individual fields to be
    overridden per test.
    """

    defaults: dict[str, object] = {
        "id": uuid4(),
        "name": "PARIKA source repository",
        "kind": KnowledgeSourceKind.REPOSITORY,
        "location": "/repo/parika",
        "status": KnowledgeSourceStatus.AVAILABLE,
    }
    defaults.update(overrides)

    return KnowledgeSource(**defaults)  # type: ignore[arg-type]


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


# ---------------------------------------------------------------------
# KnowledgeSource validation and normalization
# ---------------------------------------------------------------------


class TestKnowledgeSource:
    def test_strips_name_and_location(self) -> None:
        source = make_source(name="  My Source  ", location="  /a/b  ")

        assert source.name == "My Source"
        assert source.location == "/a/b"

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(InvalidKnowledgeSourceError):
            make_source(name="   ")

    def test_rejects_empty_location(self) -> None:
        with pytest.raises(InvalidKnowledgeSourceError):
            make_source(location="   ")

    def test_blank_description_normalized_to_none(self) -> None:
        source = make_source(description="   ")

        assert source.description is None

    def test_description_is_stripped_when_present(self) -> None:
        source = make_source(description="  hello  ")

        assert source.description == "hello"

    def test_metadata_defaults_to_empty_mapping_proxy(self) -> None:
        source = make_source()

        assert isinstance(source.metadata, MappingProxyType)
        assert dict(source.metadata) == {}

    def test_metadata_is_normalized_to_mapping_proxy(self) -> None:
        source = make_source(metadata={"branch": "main"})

        assert isinstance(source.metadata, MappingProxyType)
        assert source.metadata["branch"] == "main"

    def test_metadata_mapping_proxy_is_immutable(self) -> None:
        source = make_source(metadata={"branch": "main"})

        with pytest.raises(TypeError):
            source.metadata["branch"] = "other"  # type: ignore[index]

    def test_instance_is_frozen(self) -> None:
        source = make_source()

        with pytest.raises(FrozenInstanceError):
            source.name = "renamed"  # type: ignore[misc]

    def test_equality_and_hash_are_identity_based(self) -> None:
        shared_id = uuid4()
        first = make_source(id=shared_id, name="First", location="/a")
        second = make_source(id=shared_id, name="Second", location="/b")
        different = make_source(name="First", location="/a")

        assert first == second
        assert hash(first) == hash(second)
        assert first != different

    def test_equality_against_non_source_is_not_implemented(self) -> None:
        source = make_source()

        assert source.__eq__("not-a-source") is NotImplemented
        assert source != "not-a-source"


# ---------------------------------------------------------------------
# Knowledge validation and normalization
# ---------------------------------------------------------------------


class TestKnowledge:
    def test_strips_title_content_and_location(self) -> None:
        knowledge = make_knowledge(
            title="  Title  ",
            content="  Content  ",
            location="  loc.py:1  ",
        )

        assert knowledge.title == "Title"
        assert knowledge.content == "Content"
        assert knowledge.location == "loc.py:1"

    def test_rejects_empty_title(self) -> None:
        with pytest.raises(InvalidKnowledgeError):
            make_knowledge(title="   ")

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(InvalidKnowledgeError):
            make_knowledge(content="   ")

    def test_rejects_empty_location(self) -> None:
        with pytest.raises(InvalidKnowledgeError):
            make_knowledge(location="   ")

    def test_metadata_is_normalized_to_mapping_proxy(self) -> None:
        knowledge = make_knowledge(metadata={"language": "python"})

        assert isinstance(knowledge.metadata, MappingProxyType)
        assert knowledge.metadata["language"] == "python"

    def test_equality_and_hash_are_identity_based(self) -> None:
        shared_id = uuid4()
        first = make_knowledge(id=shared_id, title="A")
        second = make_knowledge(id=shared_id, title="B")
        different = make_knowledge(title="A")

        assert first == second
        assert hash(first) == hash(second)
        assert first != different
