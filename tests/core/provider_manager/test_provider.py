"""
Unit tests for the ProviderManager value objects: `Provider`,
`ProviderModel`, and `ModelLimits`.

Both `Provider` and `ProviderModel` are plain `@dataclass(frozen=True,
slots=True)` classes with no `__post_init__` at all (verified by
reading `provider.py` and `provider_model.py` in full) - there is no
non-empty-id validation, no metadata-immutability enforcement, and no
cross-field validation of any kind. These tests document that absence
explicitly rather than assuming validation exists, and separately
document the known `ProviderModel` metadata/hashability issue referenced
in the module docstring of `test_provider_manager.py`.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.model_limits import ModelLimits
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.state_manager.states import ProviderState


# ---------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------


class TestProvider:
    def test_defaults(self) -> None:
        provider = Provider(id="provider.ollama", name="Ollama")

        assert provider.description is None
        assert provider.state is ProviderState.DISCONNECTED
        assert provider.enabled is True
        assert provider.models == frozenset()
        assert provider.health is None
        assert provider.metadata == {}

    def test_metadata_defaults_to_immutable_mappingproxy(self) -> None:
        provider = Provider(id="provider.ollama", name="Ollama")

        assert isinstance(provider.metadata, MappingProxyType)
        with pytest.raises(TypeError):
            provider.metadata["key"] = "value"  # type: ignore[index]

    def test_is_frozen(self) -> None:
        provider = Provider(id="provider.ollama", name="Ollama")

        with pytest.raises(AttributeError):
            provider.name = "Renamed"  # type: ignore[misc]

    def test_equality_is_value_based(self) -> None:
        first = Provider(id="provider.ollama", name="Ollama")
        second = Provider(id="provider.ollama", name="Ollama")

        assert first == second
        assert first is not second

    def test_construction_does_not_validate_empty_id(self) -> None:
        """
        No `__post_init__` exists on `Provider`, so an empty `id` (or
        empty `name`) is silently accepted rather than rejected. This
        documents the current (unvalidated) behavior; it is not a bug
        per the frozen-architecture instructions, just an absence of a
        validation the docstring does not promise either.
        """

        provider = Provider(id="", name="")

        assert provider.id == ""
        assert provider.name == ""

    def test_models_field_is_not_runtime_type_checked(self) -> None:
        """
        `Provider.models` is annotated as `frozenset[ProviderModel]`
        but dataclasses do not enforce field types at runtime, so a
        plain tuple is accepted in its place. This is the workaround
        required throughout this test suite because real
        `ProviderModel` instances are unhashable (see
        `TestProviderModel` below) and therefore cannot be placed into
        an actual `frozenset`.
        """

        model = ProviderModel(id="llama3", name="Llama 3")

        provider = Provider(
            id="provider.ollama",
            name="Ollama",
            models=(model,),  # type: ignore[arg-type]
        )

        assert model in provider.models
        assert isinstance(provider.models, tuple)


# ---------------------------------------------------------------------
# ProviderModel
# ---------------------------------------------------------------------


class TestProviderModel:
    def test_defaults(self) -> None:
        model = ProviderModel(id="llama3", name="Llama 3")

        assert model.description is None
        assert model.capabilities == frozenset()
        assert model.execution_features == frozenset()
        assert model.limits == ModelLimits()
        assert model.metadata == {}

    def test_capabilities_and_execution_features_are_independent(
        self,
    ) -> None:
        model = ProviderModel(
            id="llama3",
            name="Llama 3",
            capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
            execution_features=frozenset(
                {ModelExecutionFeature.STREAMING}
            ),
        )

        assert model.capabilities == {ModelCapability.TEXT_GENERATION}
        assert model.execution_features == {
            ModelExecutionFeature.STREAMING
        }

    def test_is_frozen(self) -> None:
        model = ProviderModel(id="llama3", name="Llama 3")

        with pytest.raises(AttributeError):
            model.name = "Renamed"  # type: ignore[misc]

    def test_equality_is_value_based(self) -> None:
        first = ProviderModel(id="llama3", name="Llama 3")
        second = ProviderModel(id="llama3", name="Llama 3")

        assert first == second
        assert first is not second

    def test_construction_does_not_validate_empty_id(self) -> None:
        """
        Same absence of `__post_init__` validation as `Provider`;
        documented here rather than assumed away.
        """

        model = ProviderModel(id="", name="")

        assert model.id == ""
        assert model.name == ""

    # -------------------------------------------------------------
    # NOTE: `ProviderModel.metadata` previously defaulted to a plain
    # mutable `dict` (provider_model.py) rather than an immutable
    # `MappingProxyType` like every other metadata field in this
    # component (`Provider.metadata`, `ProviderResponse.metadata`).
    # This was fixed to use `MappingProxyType` with a `__post_init__`
    # freeze, matching every sibling immutable value object in the
    # codebase.
    #
    # Note that `MappingProxyType` itself remains unhashable (it
    # delegates `__hash__` to its underlying dict), so `ProviderModel`
    # instances are still unhashable and still cannot be placed in a
    # real `frozenset` — this is unrelated to the mutability fix and
    # is documented, not changed, below.
    # -------------------------------------------------------------

    def test_metadata_defaults_to_an_immutable_mapping(self) -> None:
        model = ProviderModel(id="llama3", name="Llama 3")

        assert isinstance(model.metadata, MappingProxyType)

    def test_metadata_cannot_be_mutated(self) -> None:
        model = ProviderModel(id="llama3", name="Llama 3")

        with pytest.raises(TypeError):
            model.metadata["injected"] = "value"  # type: ignore[index]

    def test_metadata_is_defensively_copied_from_caller_supplied_dict(
        self,
    ) -> None:
        mutable_metadata = {"trace_id": "abc"}

        model = ProviderModel(
            id="llama3",
            name="Llama 3",
            metadata=mutable_metadata,  # type: ignore[arg-type]
        )

        assert model.metadata == {"trace_id": "abc"}
        assert model.metadata is not mutable_metadata

        mutable_metadata["trace_id"] = "mutated"
        assert model.metadata["trace_id"] == "abc"

    def test_instance_is_unhashable(self) -> None:
        model = ProviderModel(id="llama3", name="Llama 3")

        with pytest.raises(TypeError, match="unhashable"):
            hash(model)

    def test_cannot_be_placed_in_a_real_frozenset(self) -> None:
        model = ProviderModel(id="llama3", name="Llama 3")

        with pytest.raises(TypeError, match="unhashable"):
            frozenset({model})

    def test_each_default_metadata_instance_is_distinct(self) -> None:
        """
        `default_factory=lambda: MappingProxyType({})` ensures separate
        `ProviderModel` instances do not accidentally share the same
        underlying mapping object.
        """

        first = ProviderModel(id="a", name="A")
        second = ProviderModel(id="b", name="B")

        assert first.metadata is not second.metadata


# ---------------------------------------------------------------------
# ModelLimits
# ---------------------------------------------------------------------


class TestModelLimits:
    def test_defaults(self) -> None:
        limits = ModelLimits()

        assert limits.context_window is None
        assert limits.max_output_tokens is None

    def test_is_frozen(self) -> None:
        limits = ModelLimits(context_window=8192)

        with pytest.raises(AttributeError):
            limits.context_window = 4096  # type: ignore[misc]

    def test_equality_is_value_based(self) -> None:
        first = ModelLimits(context_window=8192, max_output_tokens=1024)
        second = ModelLimits(context_window=8192, max_output_tokens=1024)

        assert first == second


# ---------------------------------------------------------------------
# ProviderHealth
# ---------------------------------------------------------------------


class TestProviderHealth:
    def test_defaults(self) -> None:
        health = ProviderHealth(available=True)

        assert health.latency_ms is None
        assert health.message is None

    def test_construction_does_not_validate_negative_latency(self) -> None:
        """
        No validation exists to reject a nonsensical negative latency;
        documenting current behavior rather than assuming otherwise.
        """

        health = ProviderHealth(available=True, latency_ms=-1.0)

        assert health.latency_ms == -1.0
