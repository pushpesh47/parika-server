"""
PARIKA AI Context Engineering - Prompt Builder

Owns ONLY assembling PARIKA's default Assistant Identity system prompt
from its constituent parts -- Assistant Identity (`identity.py`),
Behavior Instructions (`behavior.py`), General Constraints
(`constraints.py`), the general Reasoning Policy
(`reasoning_policy.py`), and the general Model Selection Policy
(`model_selection_policy.py`). Never sources any of that text itself,
and never decides anything about conversation, memory, knowledge,
capabilities, or tools (see the other `ai_context` submodules for
those).
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration

from . import (
    behavior,
    constraints,
    identity,
    model_selection_policy,
    reasoning_policy,
)


def build_assistant_system_prompt(configuration: Configuration) -> str:
    """
    Build PARIKA's default Assistant Identity system prompt from
    Configuration's `[assistant]` section (see `config/defaults.toml`).

    Pure function: reads only the supplied `configuration` argument --
    never a global, never a `ParikaRuntime`.     Delegates identity text
    to `identity.build_identity_text()`, fixed behavioral instructions
    to `behavior.build_behavior_text()`, general constraint text to
    `constraints.build_constraints_text()`, the general Reasoning
    Policy to `reasoning_policy.build_reasoning_policy_text()`, and the
    general Model Selection Policy to `model_selection_policy
    .build_model_selection_policy_text()`, joining every non-empty
    part with a single space -- this module owns only that assembly
    order, never the content of any part.

    `InterfaceSession.__init__()` (via `chat_capability.
    build_assistant_system_prompt()`) calls this only when its caller
    did not supply its own explicit `system_prompt`. This is what
    makes Assistant Identity automatically available to every current
    and future chat Provider without any Provider-specific code: the
    returned text becomes an ordinary first, provider-independent
    `ChatMessage(role="system", ...)` in the conversation -- exactly
    like any explicitly-supplied `system_prompt` already was, before
    this function existed. No Goal, ProviderRequest, Planner, Brain,
    ProviderManager, or Provider driver needs to know Assistant
    Identity exists.

    Args:
        configuration:
            The already-loaded Configuration to read `[assistant]`
            values from.

    Returns:
        The composed identity + behavior + constraints + reasoning
        policy text.
    """

    parts = [
        identity.build_identity_text(configuration),
        behavior.build_behavior_text(),
    ]

    constraints_text = constraints.build_constraints_text()

    if constraints_text:
        parts.append(constraints_text)

    parts.append(reasoning_policy.build_reasoning_policy_text())
    parts.append(model_selection_policy.build_model_selection_policy_text())

    return " ".join(parts)
