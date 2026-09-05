"""Environment override coverage for cloud/local routing selection."""

from parika.core.configuration.configuration import Configuration
from parika.core.planner.model_selection.routing_config import load_routing_config


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


def test_cloud_and_local_routing_configuration_resolve(monkeypatch) -> None:
    monkeypatch.setenv("PARIKA_ROUTING_TYPE", "cloud")
    monkeypatch.setenv("PARIKA_ROUTING_MODEL__MODE", "fixed")
    monkeypatch.setenv("PARIKA_ROUTING_MODEL__FIXED_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD_MODEL__FIXED_PROVIDER", "experiential_labs")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD_MODEL__FIXED_MODEL", "gpt6-astra")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD_MODEL__FALLBACK_PROVIDER", "google_gemini")
    monkeypatch.setenv("PARIKA_ROUTING__CLOUD_MODEL__FALLBACK_MODEL", "gemini-2.5-flash")
    configuration = _configuration_with_defaults({})
    configuration._apply_env_overrides()  # type: ignore[attr-defined]

    routing = load_routing_config(configuration)
    assert routing.is_fixed is True
    assert routing.fixed_model_id == "qwen3.5:4b"
    assert routing.routing_type == "cloud"
    assert (routing.cloud_fixed_provider, routing.cloud_fixed_model) == (
        "experiential_labs", "gpt6-astra"
    )
    assert (routing.cloud_fallback_provider, routing.cloud_fallback_model) == (
        "google_gemini", "gemini-2.5-flash"
    )
