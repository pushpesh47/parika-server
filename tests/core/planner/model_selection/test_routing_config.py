"""
Unit tests for `parika.core.planner.model_selection.routing_config`.

Mirrors `test_config.py`'s own shape: verifies configuration is read
exclusively through the Core `Configuration` component (never a
parallel source), with sensible, backward-compatible defaults when
`[routing_model]` - or `Configuration` itself - is absent.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.core.planner.model_selection.routing_config import (
    RoutingConfig,
    load_routing_config,
)


class _FakeConfiguration:
    """
    Minimal Configuration stand-in exposing only `.get()`, used to
    verify override behavior deterministically without depending on
    real TOML files on disk (same helper shape as `test_config.py`'s
    own `_FakeConfiguration`).
    """

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


class TestLoadRoutingConfigWithoutConfiguration:
    def test_none_configuration_defaults_to_auto(self) -> None:
        config = load_routing_config(None)

        assert config.mode == "auto"
        assert config.is_fixed is False
        assert config.fixed_model_id == ""
        assert config.fixed_provider_id is None
        assert config.fixed_thinking is False

    def test_unloaded_configuration_defaults_to_auto(self) -> None:
        config = load_routing_config(Configuration())

        assert config.mode == "auto"
        assert config.is_fixed is False


class TestLoadRoutingConfigMode:
    def test_fixed_mode_is_recognized(self) -> None:
        configuration = _FakeConfiguration({"routing_model.mode": "fixed"})

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.mode == "fixed"
        assert config.is_fixed is True

    def test_unrecognized_mode_falls_back_to_auto(self) -> None:
        configuration = _FakeConfiguration(
            {"routing_model.mode": "not-a-real-mode"}
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.mode == "auto"
        assert config.is_fixed is False

    def test_non_string_mode_falls_back_to_auto(self) -> None:
        configuration = _FakeConfiguration({"routing_model.mode": 123})

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.mode == "auto"


class TestLoadRoutingConfigFixedModel:
    def test_bare_model_id_has_no_provider(self) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "qwen3:8b",
            }
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.fixed_model_id == "qwen3:8b"
        assert config.fixed_provider_id is None

    def test_provider_qualified_model_id_is_split(self) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "provider.ollama/qwen3:8b",
            }
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.fixed_provider_id == "provider.ollama"
        assert config.fixed_model_id == "qwen3:8b"

    def test_empty_fixed_model_is_not_configured(self) -> None:
        configuration = _FakeConfiguration(
            {"routing_model.mode": "fixed"}
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.fixed_model_id == ""
        assert config.fixed_provider_id is None

    def test_non_string_fixed_model_is_not_configured(self) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": 42,
            }
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.fixed_model_id == ""


class TestLoadRoutingConfigFixedThinking:
    def test_fixed_thinking_defaults_to_false(self) -> None:
        config = load_routing_config(None)

        assert config.fixed_thinking is False

    def test_fixed_thinking_true_is_read_through_configuration(self) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_thinking": True,
            }
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.fixed_thinking is True


class TestRoutingConfigDefaults:
    def test_default_routing_config_matches_auto_backward_compatible_shape(
        self,
    ) -> None:
        assert RoutingConfig() == RoutingConfig(
            mode="auto",
            fixed_provider_id=None,
            fixed_model_id="",
            fixed_thinking=False,
        )


class TestLoadRoutingConfigLegacyNamespaceFallback:
    """
    Verifies the deprecated `[planner.routing]` namespace is still
    read as a fallback when `[routing_model]` does not define a
    given key, and that `[routing_model]` always takes precedence
    when both are present.
    """

    def test_legacy_namespace_alone_is_still_honored(self) -> None:
        configuration = _FakeConfiguration(
            {
                "planner.routing.mode": "fixed",
                "planner.routing.fixed_model": "qwen3:8b",
                "planner.routing.fixed_thinking": True,
            }
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.mode == "fixed"
        assert config.fixed_model_id == "qwen3:8b"
        assert config.fixed_thinking is True

    def test_routing_model_namespace_takes_precedence_over_legacy(
        self,
    ) -> None:
        configuration = _FakeConfiguration(
            {
                "routing_model.mode": "fixed",
                "routing_model.fixed_model": "new-model",
                "planner.routing.mode": "auto",
                "planner.routing.fixed_model": "old-model",
            }
        )

        config = load_routing_config(configuration)  # type: ignore[arg-type]

        assert config.mode == "fixed"
        assert config.fixed_model_id == "new-model"
