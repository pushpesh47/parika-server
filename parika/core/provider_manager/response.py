"""
PARIKA Core - ProviderManager Component

Defines the abstract base class for provider responses.

ProviderResponse represents a normalized response returned by a
ProviderDriver. Concrete response types inherit from this class to
represent specific AI operations such as text generation, embeddings,
vision, or speech.

ProviderResponse intentionally contains only provider-independent
information shared by every response type.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ProviderResponse(ABC):
    """
    Abstract base class for all provider responses.

    Attributes:
        model_id: str | None = None
        
        metadata:
            Optional provider-specific response metadata that does not
            belong to the normalized response contract.
    """
    model_id: str | None = None

    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )