from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from parika.core.configuration.configuration import Configuration

@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    provider_id: str
    base_url: str
    model: str
    api_key_env: str
    options: dict[str, Any]

def load_openai_compatible_configs(configuration: Configuration) -> tuple[OpenAICompatibleConfig, ...]:
    providers = configuration.get("providers", {})
    result=[]
    for provider_id, raw in providers.items():
        if (provider_id == "ollama" or not isinstance(raw, dict)
                or not raw.get("base_url") or not raw.get("model")
                or not raw.get("api_key_env")):
            continue
        result.append(OpenAICompatibleConfig(
            provider_id=provider_id, base_url=str(raw.get("base_url", "")),
            model=str(raw.get("model", "")), api_key_env=str(raw.get("api_key_env", "")),
            options={k:v for k,v in raw.items() if k not in {"base_url","model","api_key_env"}},
        ))
    return tuple(result)
