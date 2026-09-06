from types import SimpleNamespace

from parika.interfaces.ai_context.goal_decomposer import GoalDecomposer


class _Configuration:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


def test_cloud_routing_selects_configured_primary_before_local_model():
    cloud_model = SimpleNamespace(id="nvidia/nemotron-3.5-lightning:free", capabilities=frozenset())
    local_model = SimpleNamespace(id="qwen3.5:4b", capabilities=frozenset())
    provider_manager = SimpleNamespace(
        get_all=lambda: (
            SimpleNamespace(id="primary", models=(cloud_model,)),
            SimpleNamespace(id="provider.ollama", models=(local_model,)),
        )
    )
    configuration = _Configuration({
        "routing_model.mode": "fixed",
        "routing_model.fixed_model": "qwen3.5:4b",
        "routing.type": "cloud",
        # Cloud provider slot names are fixed: "primary", "secondary", "fallback"
    })
    decomposer = GoalDecomposer(
        capability_registry=None,
        provider_manager=provider_manager,
        configuration=configuration,
    )

    provider_id, model = decomposer._get_routing_model()

    assert provider_id == "primary"
    assert model is cloud_model
