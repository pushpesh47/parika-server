"""
Unit tests for the Capability Catalog metadata fields added to
`CapabilityDefinition` (`family`, `aliases`, `keywords`, `examples`,
`public`) -- all backward-compatible, defaulted fields.
"""

from __future__ import annotations

from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


class TestCatalogFieldDefaults:
    def test_public_defaults_to_true(self) -> None:
        definition = CapabilityDefinition(
            id="example.capability",
            name="Example",
            description="An example capability.",
            category=CapabilityCategory.TOOL,
        )

        assert definition.public is True

    def test_family_defaults_to_none(self) -> None:
        definition = CapabilityDefinition(
            id="example.capability",
            name="Example",
            description="An example capability.",
            category=CapabilityCategory.TOOL,
        )

        assert definition.family is None

    def test_aliases_keywords_and_examples_default_to_empty(self) -> None:
        definition = CapabilityDefinition(
            id="example.capability",
            name="Example",
            description="An example capability.",
            category=CapabilityCategory.TOOL,
        )

        assert definition.aliases == frozenset()
        assert definition.keywords == frozenset()
        assert definition.examples == ()


class TestCatalogFieldsAreSettable:
    def test_declares_a_family_and_discovery_metadata(self) -> None:
        definition = CapabilityDefinition(
            id="document.summarize",
            name="Summarize Document",
            description="Summarize a document.",
            category=CapabilityCategory.TOOL,
            family="document",
            aliases=frozenset({"tldr"}),
            keywords=frozenset({"summary", "summarize", "shorten"}),
            examples=("Summarize this PDF for me.",),
            public=True,
        )

        assert definition.family == "document"
        assert definition.aliases == frozenset({"tldr"})
        assert definition.keywords == frozenset(
            {"summary", "summarize", "shorten"}
        )
        assert definition.examples == ("Summarize this PDF for me.",)

    def test_internal_capability_can_opt_out_of_public_advertisement(
        self,
    ) -> None:
        definition = CapabilityDefinition(
            id="internal.capability",
            name="Internal",
            description="Only ever invoked directly.",
            category=CapabilityCategory.TOOL,
            public=False,
        )

        assert definition.public is False
