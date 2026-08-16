"""
PARIKA Core - ProviderManager Component

Defines the immutable ProviderModel domain object.

A ProviderModel represents a normalized artificial intelligence model
made available by a provider. It contains provider-independent metadata,
supported capabilities, execution features, and execution limits.

ProviderModel instances are discovered by ProviderDriver implementations
and consumed throughout the PARIKA Core for routing, planning, and
execution decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType

from .model_capability import ModelCapability
from .model_execution_feature import ModelExecutionFeature
from .model_limits import ModelLimits
from .model_resource_requirements import ModelResourceRequirements


@dataclass(frozen=True, slots=True)
class ProviderModel:
    """
    Immutable representation of a provider model.

    Attributes:
        id:
            Unique identifier of the model within its provider.

        name:
            Human-readable model name.

        description:
            Optional description of the model.

        capabilities:
            Intrinsic AI capabilities supported by the model.

        execution_features:
            Execution features supported by the model.

        limits:
            Normalized execution limits supported by the model.

        specializations:
            Free-form, provider-reported specialization tags
            describing which generic *task* this model was tuned or
            intended for (e.g. `"general_chat"`, `"coding"`, `"ocr"`,
            `"image_generation"`). Deliberately plain strings, not a
            closed enum: a brand new Provider or model may advertise
            a brand new specialization at any time without requiring
            a code change anywhere in PARIKA - the Model Selection
            Framework's Task Classification layer (see
            `parika/core/planner/model_selection/task_classification
            .py`) only ever compares these strings against a task's
            *required* specializations, generically. An empty set
            means the Provider did not report any specialization -
            not "this model is unspecialized" - so it is never used to
            reject a candidate on its own (see that module's
            filtering pipeline for the exact, graceful-degradation
            semantics).

        supported_modalities:
            Free-form, provider-reported input/output modality tags
            (e.g. `"text"`, `"image"`, `"audio"`, `"video"`). Same
            open, string-based extensibility rationale as
            `specializations` above - new modalities never require a
            code change.

        resource_requirements:
            Optional, normalized hardware/resource requirements this
            model declares it needs to execute (see
            `ModelResourceRequirements`). Every field of that type
            defaults to "unreported", so a model that does not
            populate it is never rejected on resource grounds.

        metadata:
            Optional provider-specific metadata that does not belong to
            the normalized ProviderModel contract.
    """

    id: str
    name: str
    description: str | None = None

    capabilities: frozenset[ModelCapability] = field(default_factory=frozenset)

    execution_features: frozenset[ModelExecutionFeature] = field(
        default_factory=frozenset
    )

    limits: ModelLimits = field(default_factory=ModelLimits)

    specializations: frozenset[str] = field(default_factory=frozenset)

    supported_modalities: frozenset[str] = field(default_factory=frozenset)

    resource_requirements: ModelResourceRequirements = field(
        default_factory=ModelResourceRequirements
    )

    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """
        Guarantee immutability of the metadata mapping and normalize
        the free-form tag sets to frozensets.
        """

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )
        object.__setattr__(
            self,
            "specializations",
            frozenset(self.specializations),
        )
        object.__setattr__(
            self,
            "supported_modalities",
            frozenset(self.supported_modalities),
        )