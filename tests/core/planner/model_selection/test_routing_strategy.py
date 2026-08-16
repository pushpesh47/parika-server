"""
Unit tests for `parika.core.planner.model_selection.routing_strategy`.

Verifies `select_fixed_routing_model()` in isolation: candidate
resolution, the unmodified hard-requirement filtering pipeline still
being the final authority, `fixed_thinking` mapping directly onto
`reasoning_enabled`/`thinking_mode`, and every "fall back to auto"
path logging a WARNING and returning `None` rather than raising.
"""

from __future__ import annotations

import logging

import pytest

from parika.core.planner.model_selection.requirements import (
    ExecutionRequirements,
    ThinkingMode,
)
from parika.core.planner.model_selection.routing_config import RoutingConfig
from parika.core.planner.model_selection.routing_strategy import (
    select_fixed_routing_model,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.state_manager.states import ProviderState

_LOGGER = logging.getLogger("test.model_selection.routing_strategy")


def _requirements(**overrides: object) -> ExecutionRequirements:
    defaults: dict[str, object] = {"capability": ModelCapability.TEXT_GENERATION}
    defaults.update(overrides)
    return ExecutionRequirements(**defaults)  # type: ignore[arg-type]


def _provider(
    provider_id: str = "provider.ollama",
    *,
    enabled: bool = True,
    health: ProviderHealth | None = None,
    models: tuple[ProviderModel, ...] = (),
) -> Provider:
    return Provider(
        id=provider_id,
        name=provider_id,
        state=ProviderState.CONNECTED,
        enabled=enabled,
        health=health,
        models=models,  # type: ignore[arg-type]
    )


def _model(model_id: str = "qwen3:8b") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
    )


class TestFixedModelResolved:
    def test_configured_model_is_selected_without_scoring(self) -> None:
        provider = _provider(models=(_model("qwen3:8b"), _model("qwen3-coder:latest")))

        result = select_fixed_routing_model(
            providers=[provider],
            requirements=_requirements(),
            routing_config=RoutingConfig(mode="fixed", fixed_model_id="qwen3:8b"),
            logger=_LOGGER,
        )

        assert result is not None
        assert result.succeeded
        assert result.selected_provider_id == "provider.ollama"
        assert result.selected_model is not None
        assert result.selected_model.id == "qwen3:8b"
        assert result.total_score is None
        assert result.breakdown == ()

    def test_provider_qualified_fixed_model_disambiguates(self) -> None:
        provider_a = _provider("provider.a", models=(_model("qwen3:8b"),))
        provider_b = _provider("provider.b", models=(_model("qwen3:8b"),))

        result = select_fixed_routing_model(
            providers=[provider_a, provider_b],
            requirements=_requirements(),
            routing_config=RoutingConfig(
                mode="fixed",
                fixed_provider_id="provider.b",
                fixed_model_id="qwen3:8b",
            ),
            logger=_LOGGER,
        )

        assert result is not None
        assert result.selected_provider_id == "provider.b"


class TestFixedThinking:
    def test_fixed_thinking_false_forces_reasoning_disabled(self) -> None:
        provider = _provider(models=(_model("qwen3:8b"),))

        result = select_fixed_routing_model(
            providers=[provider],
            requirements=_requirements(),
            routing_config=RoutingConfig(
                mode="fixed",
                fixed_model_id="qwen3:8b",
                fixed_thinking=False,
            ),
            logger=_LOGGER,
        )

        assert result is not None
        assert result.reasoning_enabled is False
        assert result.thinking_mode is ThinkingMode.OFF

    def test_fixed_thinking_true_forces_reasoning_enabled(self) -> None:
        provider = _provider(models=(_model("qwen3:8b"),))

        result = select_fixed_routing_model(
            providers=[provider],
            requirements=_requirements(),
            routing_config=RoutingConfig(
                mode="fixed",
                fixed_model_id="qwen3:8b",
                fixed_thinking=True,
            ),
            logger=_LOGGER,
        )

        assert result is not None
        assert result.reasoning_enabled is True
        assert result.thinking_mode is ThinkingMode.ON


class TestFallbackToAuto:
    def test_not_configured_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _provider(models=(_model("qwen3:8b"),))

        with caplog.at_level(logging.WARNING, logger=_LOGGER.name):
            result = select_fixed_routing_model(
                providers=[provider],
                requirements=_requirements(),
                routing_config=RoutingConfig(mode="fixed", fixed_model_id=""),
                logger=_LOGGER,
            )

        assert result is None
        assert any(
            "no fixed_model is configured" in record.message
            for record in caplog.records
        )

    def test_missing_model_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _provider(models=(_model("qwen3-coder:latest"),))

        with caplog.at_level(logging.WARNING, logger=_LOGGER.name):
            result = select_fixed_routing_model(
                providers=[provider],
                requirements=_requirements(),
                routing_config=RoutingConfig(
                    mode="fixed", fixed_model_id="qwen3:8b"
                ),
                logger=_LOGGER,
            )

        assert result is None
        assert any(
            "not registered with any Provider" in record.message
            for record in caplog.records
        )

    def test_disabled_provider_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _provider(enabled=False, models=(_model("qwen3:8b"),))

        with caplog.at_level(logging.WARNING, logger=_LOGGER.name):
            result = select_fixed_routing_model(
                providers=[provider],
                requirements=_requirements(),
                routing_config=RoutingConfig(
                    mode="fixed", fixed_model_id="qwen3:8b"
                ),
                logger=_LOGGER,
            )

        assert result is None
        assert any(
            "is unavailable" in record.message for record in caplog.records
        )

    def test_unhealthy_provider_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider = _provider(
            health=ProviderHealth(available=False),
            models=(_model("qwen3:8b"),),
        )

        with caplog.at_level(logging.WARNING, logger=_LOGGER.name):
            result = select_fixed_routing_model(
                providers=[provider],
                requirements=_requirements(),
                routing_config=RoutingConfig(
                    mode="fixed", fixed_model_id="qwen3:8b"
                ),
                logger=_LOGGER,
            )

        assert result is None
        assert any(
            "is unavailable" in record.message for record in caplog.records
        )

    def test_hard_requirement_mismatch_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Configured model exists but does not satisfy the requested
        # capability -- the unmodified `filtering.py` pipeline remains
        # the final authority even for a pinned model.
        embedding_only_model = ProviderModel(
            id="embedding-model",
            name="embedding-model",
            capabilities=frozenset({ModelCapability.EMBEDDING}),
        )
        provider = _provider(models=(embedding_only_model,))

        with caplog.at_level(logging.WARNING, logger=_LOGGER.name):
            result = select_fixed_routing_model(
                providers=[provider],
                requirements=_requirements(
                    capability=ModelCapability.TEXT_GENERATION
                ),
                routing_config=RoutingConfig(
                    mode="fixed", fixed_model_id="embedding-model"
                ),
                logger=_LOGGER,
            )

        assert result is None
        assert any(
            "is unavailable" in record.message for record in caplog.records
        )
