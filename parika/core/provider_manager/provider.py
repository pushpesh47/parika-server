"""
PARIKA Core - ProviderManager Component

Defines the immutable Provider domain object.

A Provider represents a normalized artificial intelligence provider
registered with the ProviderManager. It contains provider metadata,
its discovered models, and current health information.

Provider instances are immutable snapshots of a provider's
connectivity state, discovered models, and health information.
Runtime operations are performed by the associated ProviderDriver.

Provider capabilities are intentionally not stored as part of the
Provider domain object. They are derived from the capabilities of the
registered ProviderModel instances when needed to avoid duplicated
state and ensure consistency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from parika.core.state_manager.states import ProviderState

from .provider_health import ProviderHealth
from .provider_model import ProviderModel


@dataclass(frozen=True, slots=True)
class Provider:
    """
    Immutable representation of a registered AI provider.

    Attributes:
        id:
            Unique identifier of the provider.

        name:
            Human-readable provider name.

        description:
            Optional description of the provider.

        state:
            Current connectivity state of the provider.

        enabled:
            Indicates whether the provider is enabled for routing.

        models:
            Models currently discovered for this provider.

        health:
            Latest normalized health information reported by the provider.

        metadata:
            Optional provider-specific metadata that does not belong to
            the normalized Provider contract.
    """

    id: str
    name: str
    description: str | None = None

    state: ProviderState = ProviderState.DISCONNECTED
    enabled: bool = True

    models: frozenset[ProviderModel] = field(default_factory=frozenset)

    health: ProviderHealth | None = None

    metadata: Mapping[str, object] = field(
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