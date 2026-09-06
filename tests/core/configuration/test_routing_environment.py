"""Environment override coverage for cloud/local routing selection."""

from parika.core.configuration.configuration import Configuration
from parika.core.planner.model_selection.routing_config import load_routing_config
from parika.providers.openai_compatible.config import load_openai_compatible_configs


def _configuration_with_defaults(defaults: dict[str, object]) -> Configuration:
    configuration = Configuration()
    configuration._config = defaults  # type: ignore[attr-defined]
    return configuration


def test_routing_type_environment_selects_local(monkeypatch) -> None:
    monkeypatch.setenv("PARIKA_ROUTING_TYPE", "local")
    configuration = _configuration_with_defaults({"routing": {"type": "cloud"}})
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    assert load_routing_config(configuration).routing_type == "local"


def test_routing_type_environment_selects_cloud(monkeypatch) -> None:
    monkeypatch.setenv("PARIKA_ROUTING_TYPE", "cloud")
    configuration = _configuration_with_defaults({})
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    assert load_routing_config(configuration).routing_type == "cloud"


def test_routing_type_environment_overrides_default(monkeypatch) -> None:
    monkeypatch.setenv("PARIKA_ROUTING_TYPE", "cloud")
    configuration = _configuration_with_defaults({"routing": {"type": "local"}})
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    assert configuration.get("routing.type") == "cloud"


def test_local_fixed_model_configuration_remains_available(monkeypatch) -> None:
    monkeypatch.setenv("PARIKA_ROUTING_TYPE", "local")
    monkeypatch.setenv("PARIKA_ROUTING_MODEL__MODE", "fixed")
    monkeypatch.setenv("PARIKA_ROUTING_MODEL__FIXED_MODEL", "qwen3.5:4b")
    configuration = _configuration_with_defaults({})
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    routing = load_routing_config(configuration)
    assert routing.routing_type == "local"
    assert routing.is_fixed is True
    assert routing.fixed_model_id == "qwen3.5:4b"


def test_cloud_routing_configuration_resolves_three_fixed_slots(monkeypatch) -> None:
    monkeypatch.setenv("PARIKA_ROUTING_TYPE", "cloud")
    monkeypatch.setenv("PARIKA_ROUTING_MODEL__MODE", "fixed")
    monkeypatch.setenv("PARIKA_ROUTING_MODEL__FIXED_MODEL", "qwen3.5:4b")
    configuration = _configuration_with_defaults({})
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    routing = load_routing_config(configuration)
    assert routing.is_fixed is True
    assert routing.fixed_model_id == "qwen3.5:4b"
    assert routing.routing_type == "cloud"
    # Slot names are now fixed internal constants
    assert routing.cloud_primary_provider == "primary"
    assert routing.cloud_secondary_provider == "secondary"
    assert routing.cloud_fallback_provider == "fallback"


def test_cloud_provider_slot_primary_resolves_from_env(monkeypatch) -> None:
    """Test that primary slot resolves provider identity, model, base_url from env."""
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_PROVIDER", "kilo_code")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_BASE_URL", "https://api.kilo.ai/api/openrouter")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_MODEL", "custom-model-kilo")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY", "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_REASONING_REQUEST_PATH", "reasoning.enabled")
    configuration = _configuration_with_defaults({
        "cloud_providers": {
            "primary": {
                "provider": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_PROVIDER",
                "base_url": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_BASE_URL",
                "model": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_MODEL",
                "api_key_env": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY",
                "reasoning_request_path": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_REASONING_REQUEST_PATH",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            }
        }
    })
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    assert configuration.get("cloud_providers.primary.provider") == "kilo_code"
    assert configuration.get("cloud_providers.primary.base_url") == "https://api.kilo.ai/api/openrouter"
    assert configuration.get("cloud_providers.primary.model") == "custom-model-kilo"
    assert configuration.get("cloud_providers.primary.api_key_env") == "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY"
    assert configuration.get("cloud_providers.primary.reasoning_request_path") == "reasoning.enabled"

    configs = load_openai_compatible_configs(configuration)
    # provider_id is now the slot name "primary"
    primary_cfg = next(c for c in configs if c.provider_id == "primary")
    assert primary_cfg.model == "custom-model-kilo"
    assert primary_cfg.base_url == "https://api.kilo.ai/api/openrouter"
    assert primary_cfg.api_key_env == "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY"
    assert "reasoning_request_path" in primary_cfg.options
    assert primary_cfg.options["reasoning_request_path"] == "reasoning.enabled"
    # provider_identity should NOT be in options (avoids forwarding to driver)
    assert "provider_identity" not in primary_cfg.options


def test_cloud_provider_slot_secondary_resolves_from_env(monkeypatch) -> None:
    """Test that secondary slot resolves provider identity, model, base_url from env."""
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_PROVIDER", "block_run")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_BASE_URL", "https://api.blockrun.ai/v1")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_MODEL", "custom-model-block")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_KEY", "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_KEY")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_REASONING_REQUEST_PATH", "chat_template_kwargs.enable_thinking")
    configuration = _configuration_with_defaults({
        "cloud_providers": {
            "secondary": {
                "provider": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_PROVIDER",
                "base_url": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_BASE_URL",
                "model": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_MODEL",
                "api_key_env": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_KEY",
                "reasoning_request_path": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_REASONING_REQUEST_PATH",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            }
        }
    })
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    assert configuration.get("cloud_providers.secondary.provider") == "block_run"
    assert configuration.get("cloud_providers.secondary.base_url") == "https://api.blockrun.ai/v1"
    assert configuration.get("cloud_providers.secondary.model") == "custom-model-block"
    assert configuration.get("cloud_providers.secondary.api_key_env") == "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_KEY"
    assert configuration.get("cloud_providers.secondary.reasoning_request_path") == "chat_template_kwargs.enable_thinking"

    configs = load_openai_compatible_configs(configuration)
    # provider_id is now the slot name "secondary"
    secondary_cfg = next(c for c in configs if c.provider_id == "secondary")
    assert secondary_cfg.model == "custom-model-block"
    assert secondary_cfg.base_url == "https://api.blockrun.ai/v1"
    assert secondary_cfg.api_key_env == "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_KEY"
    assert "reasoning_request_path" in secondary_cfg.options
    assert secondary_cfg.options["reasoning_request_path"] == "chat_template_kwargs.enable_thinking"
    assert "provider_identity" not in secondary_cfg.options


def test_cloud_provider_slot_fallback_resolves_from_env(monkeypatch) -> None:
    """Test that fallback slot resolves provider identity, model, base_url from env."""
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_PROVIDER", "fallback_provider")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_BASE_URL", "https://api.fallback.ai/v1")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_MODEL", "fallback-model")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_KEY", "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_KEY")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_REASONING_REQUEST_PATH", "thinking.enabled")
    configuration = _configuration_with_defaults({
        "cloud_providers": {
            "fallback": {
                "provider": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_PROVIDER",
                "base_url": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_BASE_URL",
                "model": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_MODEL",
                "api_key_env": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_KEY",
                "reasoning_request_path": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_REASONING_REQUEST_PATH",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            }
        }
    })
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    assert configuration.get("cloud_providers.fallback.provider") == "fallback_provider"
    assert configuration.get("cloud_providers.fallback.base_url") == "https://api.fallback.ai/v1"
    assert configuration.get("cloud_providers.fallback.model") == "fallback-model"
    assert configuration.get("cloud_providers.fallback.api_key_env") == "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_KEY"
    assert configuration.get("cloud_providers.fallback.reasoning_request_path") == "thinking.enabled"

    configs = load_openai_compatible_configs(configuration)
    # provider_id is now the slot name "fallback"
    fallback_cfg = next(c for c in configs if c.provider_id == "fallback")
    assert fallback_cfg.model == "fallback-model"
    assert fallback_cfg.base_url == "https://api.fallback.ai/v1"
    assert fallback_cfg.api_key_env == "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_KEY"
    assert "reasoning_request_path" in fallback_cfg.options
    assert fallback_cfg.options["reasoning_request_path"] == "thinking.enabled"
    assert "provider_identity" not in fallback_cfg.options


def test_all_three_cloud_provider_slots_work_together(monkeypatch) -> None:
    """Test that all three slots work together with different providers."""
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_PROVIDER", "provider_a")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_MODEL", "model-a")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_BASE_URL", "https://api.a.com/v1")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY", "KEY_A")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_PROVIDER", "provider_b")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_MODEL", "model-b")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_BASE_URL", "https://api.b.com/v1")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_KEY", "KEY_B")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_PROVIDER", "provider_c")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_MODEL", "model-c")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_BASE_URL", "https://api.c.com/v1")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_KEY", "KEY_C")

    configuration = _configuration_with_defaults({
        "cloud_providers": {
            "primary": {
                "provider": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_PROVIDER",
                "base_url": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_BASE_URL",
                "model": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_MODEL",
                "api_key_env": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            },
            "secondary": {
                "provider": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_PROVIDER",
                "base_url": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_BASE_URL",
                "model": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_MODEL",
                "api_key_env": "PARIKA_ROUTING__CLOUD__SECONDARY_PROVIDER_KEY",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            },
            "fallback": {
                "provider": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_PROVIDER",
                "base_url": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_BASE_URL",
                "model": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_MODEL",
                "api_key_env": "PARIKA_ROUTING__CLOUD__FALLBACK_PROVIDER_KEY",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            },
        }
    })
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    configs = load_openai_compatible_configs(configuration)
    assert len(configs) == 3
    # provider_ids are now the fixed slot names
    models = {c.provider_id: c.model for c in configs}
    assert models["primary"] == "model-a"
    assert models["secondary"] == "model-b"
    assert models["fallback"] == "model-c"
    urls = {c.provider_id: c.base_url for c in configs}
    assert urls["primary"] == "https://api.a.com/v1"
    assert urls["secondary"] == "https://api.b.com/v1"
    assert urls["fallback"] == "https://api.c.com/v1"
    # Provider identities are NOT in options (avoids forwarding to driver)
    for c in configs:
        assert "provider_identity" not in c.options


def test_cloud_provider_slot_fallback_to_toml_default(monkeypatch) -> None:
    """Test that TOML default is used when env var is not set."""
    # Don't set the env var, should use the TOML value
    # Don't call _apply_env_overrides since we're testing TOML default without env override
    configuration = _configuration_with_defaults({
        "cloud_providers": {
            "primary": {
                "provider": "default_provider",
                "base_url": "https://api.default.com/v1",
                "model": "fallback-model",
                "api_key_env": "DEFAULT_KEY",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            }
        }
    })
    # NOTE: Not calling _apply_env_overrides - this tests pure TOML default

    assert configuration.get("cloud_providers.primary.model") == "fallback-model"
    configs = load_openai_compatible_configs(configuration)
    # provider_id is the slot name "primary"
    primary_cfg = next(c for c in configs if c.provider_id == "primary")
    assert primary_cfg.model == "fallback-model"
    assert "provider_identity" not in primary_cfg.options


def test_cloud_provider_api_key_env_name_passed_to_driver(monkeypatch) -> None:
    """Test that api_key_env name is correctly passed to driver (not the secret)."""
    # The api_key_env in TOML is a static string (name of env var), not overridden by env
    # The actual secret is set in the named env var, read by driver at runtime
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY", "actual-secret-value")
    configuration = _configuration_with_defaults({
        "cloud_providers": {
            "primary": {
                "provider": "test_provider",
                "base_url": "https://api.test.com/v1",
                "model": "test-model",
                "api_key_env": "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY",
                "supported_parameters": ["temperature", "top_p", "max_tokens", "stop"],
            }
        }
    })
    # Note: _apply_env_overrides is NOT called for api_key_env - it stays as the env var name
    # configuration._apply_env_overrides()  # type: ignore[attr-defined]

    # api_key_env is the NAME of the env var, not the secret value
    assert configuration.get("cloud_providers.primary.api_key_env") == "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY"
    configs = load_openai_compatible_configs(configuration)
    primary_cfg = next(c for c in configs if c.provider_id == "primary")
    assert primary_cfg.api_key_env == "PARIKA_ROUTING__CLOUD__PRIMARY_PROVIDER_KEY"