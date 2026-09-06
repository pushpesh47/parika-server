from types import SimpleNamespace
from pathlib import Path
import tomllib
from parika.providers.openai_compatible.config import load_openai_compatible_configs

def test_loads_multiple_arbitrary_providers():
    cfg = SimpleNamespace(get=lambda key, default=None: {
        "cloud_providers": {
            "primary": {"provider": "alpha", "base_url": "https://a/v1", "model": "a", "api_key_env": "KEY_A"},
            "secondary": {"provider": "beta", "base_url": "https://b/v1", "model": "b", "api_key_env": "KEY_B"},
        }
    }.get(key, default))
    values = load_openai_compatible_configs(cfg)
    # provider_id is now the slot name; provider identity is metadata in TOML but NOT passed to driver
    # (driver doesn't accept provider_identity parameter)
    assert [(v.provider_id, v.model, v.api_key_env) for v in values] == [
        ("primary", "a", "KEY_A"),
        ("secondary", "b", "KEY_B"),
    ]
    # provider_identity should NOT be in options (avoids forwarding to driver)
    for v in values:
        assert "provider_identity" not in v.options

def test_cloud_provider_slots_use_strict_shape():
    with Path("config/defaults.toml").open("rb") as stream:
        data = tomllib.load(stream)
    # Verify cloud_providers section exists with three slots
    assert "cloud_providers" in data
    assert "primary" in data["cloud_providers"]
    assert "secondary" in data["cloud_providers"]
    assert "fallback" in data["cloud_providers"]
    # Verify each slot has the required fields
    for slot in ["primary", "secondary", "fallback"]:
        provider = data["cloud_providers"][slot]
        assert "provider" in provider
        assert "base_url" in provider
        assert "model" in provider
        assert "api_key_env" in provider
        assert "supported_parameters" in provider
        assert "reasoning_request_path" in provider
