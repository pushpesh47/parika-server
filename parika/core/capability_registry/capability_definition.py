"""
Immutable capability definition.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .capability_category import CapabilityCategory


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityDefinition:
    """
    Immutable definition of a capability registered with PARIKA.
    """

    id: str
    name: str
    description: str
    category: CapabilityCategory

    version: str = "1.0.0"

    provider: str | None = None
    source: str | None = None

    tags: frozenset[str] = field(default_factory=frozenset)

    enabled: bool = True

    public: bool = True
    """
    Whether this Capability may ever be advertised to a router/chat
    model as a candidate tool. Internal-only capabilities (e.g. those
    only ever invoked directly by another Core component, never by a
    model) should set this to False; the Capability Catalog's
    deterministic filtering stage excludes non-public capabilities
    unconditionally.
    """

    family: str | None = None
    """
    Optional retrieval-time grouping identifier (e.g. "document",
    "vision", "ocr", "coding"). Families are a Capability Catalog
    retrieval concept only -- they group related leaf capabilities for
    ranking purposes and are never executable, never a Module, and
    never advertised to a router/chat model in place of a leaf
    capability. A Capability with no `family` is treated by the
    catalog as belonging to a fallback family derived from its
    `category`.
    """

    aliases: frozenset[str] = field(default_factory=frozenset)
    """
    Optional alternative names for this capability, used only by the
    Capability Catalog's lexical retrieval stage alongside `name`.
    """

    keywords: frozenset[str] = field(default_factory=frozenset)
    """
    Optional free-form retrieval keywords, used only by the Capability
    Catalog's lexical retrieval stage. Distinct from `tags`, which
    remain indexed by `CapabilityRegistry` for exact lookup.
    """

    examples: tuple[str, ...] = field(default_factory=tuple)
    """
    Optional example phrasings of requests this capability satisfies,
    used only by the Capability Catalog's lexical retrieval stage.
    """

    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """
        Guarantee immutability of the metadata mapping.
        """

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )