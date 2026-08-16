"""
PARIKA AI Context Engineering - Model Selection Policy

Owns ONLY the general, capability-independent instruction that tells
the routing model (the chat model handling this turn) that it may
optionally provide AI-assisted model-selection guidance when it calls
a tool whose execution will be delegated to a specialized, Provider-
backed model -- and exactly how to provide it.

This policy never mentions a specific Capability id, tool name, model
name, or task name, of any current or future domain -- exactly the
same generic contract `reasoning_policy.py` already follows. It
describes only:

    - That an inventory of other installed AI models may appear
      elsewhere in this turn's context (see `worker_inventory.py`,
      which renders that inventory, when there is one to render).
    - The one reserved, generic tool-call argument
      (`model_selection_hint`) any tool call MAY optionally carry,
      and its shape.

Providing this hint is always optional. Every tool continues to work
exactly as before when it is omitted -- this policy, and the
`model_selection_hint` argument it describes, never changes what a
tool call otherwise requires (see `parika/providers/ollama
/tool_calling.py`, which extracts this one reserved key before a
tool's own arguments are used, and
`parika/core/planner/model_selection/rules.py`'s
`RoutingRecommendationRule`, which treats an absent or malformed hint
as a neutral no-op, never an error).
"""

from __future__ import annotations

MODEL_SELECTION_POLICY = (
    "When you decide to call a tool whose execution will be handled "
    "by a specialized AI model (for example, one that performs "
    "vision, OCR, or code generation), you may optionally include an "
    "additional top-level argument named \"model_selection_hint\" in "
    "that tool call, alongside the tool's own normal arguments. This "
    "argument is always optional and never required. "
    "If an inventory of other installed AI models is provided "
    "elsewhere in this conversation, use it to decide whether a "
    "recommendation is worth making; you are never required to "
    "recommend a model you are not confident about. "
    "\"model_selection_hint\" may contain: "
    "\"candidate_models\", a ranked list of objects like "
    "{\"provider_id\": ..., \"model_id\": ..., \"confidence\": 0.0-1.0}, "
    "naming only models that already appear in that inventory; and "
    "\"reasoning_level\", one of \"simple\", \"normal\", or \"complex\", "
    "describing how much extended reasoning (\"thinking\") the "
    "downstream execution actually needs -- for example \"simple\" for "
    "straightforward extraction or generation, \"complex\" for "
    "difficult multi-step analysis. The final choice of model, and "
    "whether thinking is actually enabled, always remains PARIKA's "
    "own decision; this hint only helps narrow that decision, it "
    "never replaces it."
)
"""
Fixed general model-selection policy text appended to the system
prompt (see `prompt_builder.build_assistant_system_prompt()`).
Deliberately not sourced from `[assistant]` configuration and
deliberately silent about any specific Capability/Tool/model/task --
see the module docstring.
"""


def build_model_selection_policy_text() -> str:
    """
    Return the fixed general model-selection policy text.

    Pure function, no arguments: this text never varies by
    Configuration, by turn, or by which Capabilities happen to be
    enabled.
    """

    return MODEL_SELECTION_POLICY
