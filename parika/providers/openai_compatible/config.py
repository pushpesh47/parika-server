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

CLOUD_PROVIDER_SLOTS = ("primary", "secondary", "fallback")

def load_openai_compatible_configs(configuration: Configuration) -> tuple[OpenAICompatibleConfig, ...]:
    cloud_providers = configuration.get("cloud_providers", {})
    result = []
    for slot in CLOUD_PROVIDER_SLOTS:
        raw = cloud_providers.get(slot)
        if not isinstance(raw, dict):
            continue
        # Use slot name as provider_id for routing; provider identity is metadata only
        provider_identity = str(raw.get("provider", slot))
        base_url = str(raw.get("base_url", ""))
        model = str(raw.get("model", ""))
        api_key_env = str(raw.get("api_key_env", ""))
        if not base_url or not model or not api_key_env:
            continue
        # Exclude provider_identity from options to avoid forwarding to driver constructor
        # (driver doesn't accept provider_identity parameter)
        options = {k: v for k, v in raw.items() if k not in {"base_url", "model", "api_key_env", "provider", "provider_identity"}}
        result.append(OpenAICompatibleConfig(
            provider_id=slot,
            base_url=base_url,
            model=model,
            api_key_env=api_key_env,
            options=options,
        ))
    return tuple(result)
