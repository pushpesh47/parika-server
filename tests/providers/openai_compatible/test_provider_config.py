from types import SimpleNamespace
from pathlib import Path
import tomllib
from parika.providers.openai_compatible.config import load_openai_compatible_configs

def test_loads_multiple_arbitrary_providers():
    cfg = SimpleNamespace(get=lambda key, default=None: {
        "providers": {
            "alpha": {"base_url":"https://a/v1","model":"a","api_key_env":"KEY_A"},
            "beta": {"base_url":"https://b/v1","model":"b","api_key_env":"KEY_B"},
        }
    }.get(key, default))
    values = load_openai_compatible_configs(cfg)
    assert [(v.provider_id, v.model, v.api_key_env) for v in values] == [("alpha","a","KEY_A"),("beta","b","KEY_B")]

def test_experiential_labs_defaults_use_strict_three_field_shape():
    with Path("config/defaults.toml").open("rb") as stream:
        data = tomllib.load(stream)
    provider = data["providers"]["experiential_labs"]
    assert provider == {
        "base_url": "https://api.experientiallabs.ai/v1",
        "model": "gpt6-astra",
        "api_key_env": "PARIKA_PROVIDER_EXPERIENTIAL_LABS_API_KEY",
    }
    assert "routing" not in data
