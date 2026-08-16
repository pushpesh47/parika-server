"""
Unit tests for `parika.core.planner.model_selection.filtering`.
"""

from __future__ import annotations

from parika.core.planner.model_selection.filtering import (
    evaluate_hard_requirements,
)
from parika.core.planner.model_selection.requirements import (
    ExecutionRequirements,
    Requirement,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import (
    ModelExecutionFeature,
)
from parika.core.provider_manager.model_limits import ModelLimits
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel


def _provider(**overrides: object) -> Provider:
    return Provider(id="provider.test", name="Test", **overrides)  # type: ignore[arg-type]


def _model(**overrides: object) -> ProviderModel:
    defaults: dict[str, object] = {
        "id": "model-a",
        "name": "Model A",
        "capabilities": frozenset({ModelCapability.TEXT_GENERATION}),
    }
    defaults.update(overrides)
    return ProviderModel(**defaults)  # type: ignore[arg-type]


def _requirements(**overrides: object) -> ExecutionRequirements:
    defaults: dict[str, object] = {"capability": ModelCapability.TEXT_GENERATION}
    defaults.update(overrides)
    return ExecutionRequirements(**defaults)  # type: ignore[arg-type]


class TestProviderLevelRejections:
    def test_rejects_disabled_provider(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(enabled=False), _model(), _requirements()
        )

        assert reason == "provider is disabled"

    def test_rejects_unavailable_provider(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(health=ProviderHealth(available=False)),
            _model(),
            _requirements(),
        )

        assert reason == "provider is unavailable"

    def test_accepts_provider_with_unknown_health(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(health=None), _model(), _requirements()
        )

        assert reason is None

    def test_accepts_available_provider(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(health=ProviderHealth(available=True)),
            _model(),
            _requirements(),
        )

        assert reason is None


class TestModelLevelRejections:
    def test_rejects_missing_required_capability(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(capabilities=frozenset({ModelCapability.EMBEDDING})),
            _requirements(capability=ModelCapability.TEXT_GENERATION),
        )

        assert reason is not None
        assert "text_generation" in reason

    def test_rejects_missing_required_tool_calling(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(tool_calling=Requirement.REQUIRED),
        )

        assert reason == "model does not support required tool calling"

    def test_accepts_preferred_tool_calling_without_support(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(tool_calling=Requirement.PREFERRED),
        )

        assert reason is None

    def test_rejects_missing_required_vision(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(vision=Requirement.REQUIRED),
        )

        assert reason == "model does not support required vision input"

    def test_accepts_model_with_required_vision_support(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.VISION}
                )
            ),
            _requirements(vision=Requirement.REQUIRED),
        )

        assert reason is None

    def test_rejects_missing_required_structured_output(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(structured_output=Requirement.REQUIRED),
        )

        assert reason == (
            "model does not support required structured output"
        )

    def test_rejects_insufficient_context_window(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(limits=ModelLimits(context_window=2048)),
            _requirements(min_context_window=8192),
        )

        assert reason is not None
        assert "context window" in reason

    def test_rejects_missing_context_window_when_required(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(limits=ModelLimits(context_window=None)),
            _requirements(min_context_window=8192),
        )

        assert reason is not None

    def test_accepts_sufficient_context_window(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(limits=ModelLimits(context_window=16384)),
            _requirements(min_context_window=8192),
        )

        assert reason is None

    def test_accepts_fully_compatible_model(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                execution_features=frozenset(
                    {ModelExecutionFeature.TOOL_CALLING}
                )
            ),
            _requirements(tool_calling=Requirement.PREFERRED),
        )

        assert reason is None


class TestSpecializationFiltering:
    """
    Step 1 of the pipeline: reject a model whose *declared*
    specializations do not include any required one. A model that
    reports no specializations at all is never rejected on this
    dimension -- specialization is optional, best-effort metadata.
    """

    def test_rejects_model_specialized_for_a_different_task(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(specializations=frozenset({"ocr"})),
            _requirements(required_specializations=frozenset({"general_chat"})),
        )

        assert reason is not None
        assert "ocr" in reason

    def test_accepts_model_matching_a_required_specialization(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(specializations=frozenset({"general_chat", "reasoning"})),
            _requirements(required_specializations=frozenset({"general_chat"})),
        )

        assert reason is None

    def test_accepts_model_reporting_no_specializations_at_all(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(required_specializations=frozenset({"general_chat"})),
        )

        assert reason is None

    def test_no_requirement_never_filters_on_specialization(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(specializations=frozenset({"ocr"})),
            _requirements(),
        )

        assert reason is None


class TestModalityFiltering:
    """
    Step 3 of the pipeline: same graceful-degradation contract as
    specialization filtering, applied to `supported_modalities`.
    """

    def test_rejects_model_missing_required_modality(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(supported_modalities=frozenset({"text"})),
            _requirements(required_modalities=frozenset({"image"})),
        )

        assert reason is not None
        assert "image" in reason

    def test_accepts_model_matching_a_required_modality(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(supported_modalities=frozenset({"text", "image"})),
            _requirements(required_modalities=frozenset({"image"})),
        )

        assert reason is None

    def test_accepts_model_reporting_no_modalities_at_all(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(required_modalities=frozenset({"image"})),
        )

        assert reason is None


class TestAdditionalCapabilityAndExecutionFeatureFiltering:
    """
    Step 2 of the pipeline: `required_capabilities`/
    `required_execution_features` are always hard-enforced when
    non-empty, unlike specializations/modalities.
    """

    def test_rejects_model_missing_a_required_capability(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(
                required_capabilities=frozenset({ModelCapability.CODING})
            ),
        )

        assert reason is not None
        assert "coding" in reason

    def test_accepts_model_with_required_capabilities(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                capabilities=frozenset(
                    {ModelCapability.TEXT_GENERATION, ModelCapability.CODING}
                )
            ),
            _requirements(
                required_capabilities=frozenset({ModelCapability.CODING})
            ),
        )

        assert reason is None

    def test_rejects_model_missing_a_required_execution_feature(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(
                required_execution_features=frozenset(
                    {ModelExecutionFeature.TOOL_CALLING}
                )
            ),
        )

        assert reason is not None
        assert "tool_calling" in reason

    def test_accepts_model_with_required_execution_features(self) -> None:
        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                execution_features=frozenset(
                    {ModelExecutionFeature.TOOL_CALLING}
                )
            ),
            _requirements(
                required_execution_features=frozenset(
                    {ModelExecutionFeature.TOOL_CALLING}
                )
            ),
        )

        assert reason is None


class TestResourceFiltering:
    """
    Step 7 of the pipeline: resource validation is skipped entirely
    (never a rejection) unless both a snapshot is supplied *and* the
    model actually declares the corresponding requirement.
    """

    def test_no_snapshot_never_rejects(self) -> None:
        from parika.core.provider_manager.model_resource_requirements import (
            ModelResourceRequirements,
        )

        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                resource_requirements=ModelResourceRequirements(
                    min_ram_bytes=1_000_000_000_000,
                )
            ),
            _requirements(),
        )

        assert reason is None

    def test_insufficient_ram_is_rejected(self) -> None:
        from parika.core.provider_manager.model_resource_requirements import (
            ModelResourceRequirements,
        )

        snapshot = _resource_snapshot(available_ram_bytes=1_000)

        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                resource_requirements=ModelResourceRequirements(
                    min_ram_bytes=1_000_000,
                )
            ),
            _requirements(available_resources=snapshot),
        )

        assert reason is not None
        assert "RAM" in reason

    def test_sufficient_ram_is_accepted(self) -> None:
        from parika.core.provider_manager.model_resource_requirements import (
            ModelResourceRequirements,
        )

        snapshot = _resource_snapshot(available_ram_bytes=1_000_000_000)

        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                resource_requirements=ModelResourceRequirements(
                    min_ram_bytes=1_000_000,
                )
            ),
            _requirements(available_resources=snapshot),
        )

        assert reason is None

    def test_missing_gpu_is_rejected_when_required(self) -> None:
        from parika.core.provider_manager.model_resource_requirements import (
            ModelResourceRequirements,
        )

        snapshot = _resource_snapshot(gpu_available=False)

        reason = evaluate_hard_requirements(
            _provider(),
            _model(
                resource_requirements=ModelResourceRequirements(
                    requires_gpu=True,
                )
            ),
            _requirements(available_resources=snapshot),
        )

        assert reason is not None
        assert "GPU" in reason

    def test_unreported_requirement_is_never_rejected(self) -> None:
        snapshot = _resource_snapshot(
            available_ram_bytes=1_000, gpu_available=False
        )

        reason = evaluate_hard_requirements(
            _provider(),
            _model(),
            _requirements(available_resources=snapshot),
        )

        assert reason is None


def _resource_snapshot(
    *,
    available_ram_bytes: int = 1_000_000_000,
    free_disk_bytes: int = 1_000_000_000,
    gpu_available: bool = True,
) -> object:
    from datetime import UTC, datetime
    from pathlib import Path

    from parika.core.resource_manager.models import (
        CPUInfo,
        DiskInfo,
        FilesystemInfo,
        GPUInfo,
        MemoryInfo,
        NetworkInfo,
        ResourceSnapshot,
        SystemInfo,
        TemperatureInfo,
    )
    from parika.core.resource_manager.resource_status import ResourceStatus

    return ResourceSnapshot(
        cpu=CPUInfo(
            usage_percent=0.0, logical_core_count=1, physical_core_count=1
        ),
        memory=MemoryInfo(
            total_bytes=free_disk_bytes,
            available_bytes=available_ram_bytes,
            used_bytes=0,
        ),
        disk=DiskInfo(
            path=Path("/"),
            total_bytes=free_disk_bytes,
            free_bytes=free_disk_bytes,
            used_bytes=0,
        ),
        gpu=GPUInfo(
            status=(
                ResourceStatus.AVAILABLE
                if gpu_available
                else ResourceStatus.UNAVAILABLE
            ),
            detected=gpu_available,
        ),
        network=NetworkInfo(status=ResourceStatus.UNKNOWN, hostname=None),
        filesystem=FilesystemInfo(status=ResourceStatus.UNKNOWN, paths=()),
        temperature=TemperatureInfo(status=ResourceStatus.UNKNOWN),
        system=SystemInfo(
            platform="Linux",
            operating_system="Linux",
            kernel_release=None,
            architecture="x86_64",
            hostname=None,
            boot_time=None,
            uptime_seconds=None,
            uptime_human=None,
        ),
        timestamp=datetime.now(UTC),
    )
