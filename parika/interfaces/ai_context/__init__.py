"""
PARIKA AI Context Engineering Subsystem

Dedicated, modular subsystem responsible for dynamically constructing
the AI's runtime worldview for one chat turn -- who PARIKA is, what it
can currently do, and the conversation/memory/knowledge/session
context relevant to this turn -- and assembling it into the `Goal`
`Brain.handle()` receives. `parika/interfaces/chat_capability.py`
remains the thin orchestration entry point Interfaces call into; every
submodule here owns exactly one responsibility and contains no
knowledge of any other submodule's job.

Two first-class concerns, both owned entirely within this one package
(no new component, no new pipeline stage):

    Context Engineering -- "what information should the model
    receive?" Conversation, Memory, Knowledge, Retrieved Context, and
    Context Assembly: `context_builder.py` (+ `memory.py`/
    `knowledge.py`), `session_context.py`, `conversation.py`.

    Prompt Engineering -- "how should that information be presented
    to the model?" Assistant Identity, Behavior, Constraints,
    Reasoning Policy, Model Selection Policy, Worker Inventory, Tool
    Descriptions, and Final Prompt Assembly: `identity.py`,
    `behavior.py`, `constraints.py`, `reasoning_policy.py`,
    `model_selection_policy.py`, `prompt_builder.py`,
    `capability_context.py` + `tool_context.py`, `worker_inventory.py`,
    and `goal_builder.py` (Final Prompt Assembly -- see that module's
    own docstring for how it also measures the one, complete assembled
    prompt for the Runtime Context Budget, exactly once, rather than
    summing named parts).

Every submodule below still belongs to exactly one of these two
concerns; the grouping above is a naming/documentation clarification
of an already-existing split, not a code reorganization -- no
submodule moved, and Context Engineering's output (the effective
conversation, already including retrieved Memory/Knowledge/Session
content) is simply Prompt Engineering's own input, via the same
`messages` argument `goal_builder.build_chat_goal()` already received
before this distinction was named explicitly.

    identity.py            Assistant identity text only.
    behavior.py             Fixed behavioral operating instructions only.
    constraints.py          General constraint text only (currently none).
    reasoning_policy.py      General, capability-independent reasoning
                             policy only (source-preference ordering;
                             never mentions a specific Capability).
    model_selection_policy.py General, capability-independent policy
                             describing the optional, reserved
                             `model_selection_hint` tool-call argument
                             (AI-assisted model-selection refinement).
                             Never mentions a specific Capability,
                             tool, model, or task name.
    prompt_builder.py       Combines identity/behavior/constraints/
                             reasoning policy/model selection policy
                             into the system prompt. Owns no prompt
                             content itself.
    conversation.py          Splices retrieved context into the rolling
                             conversation message list. Never retrieves
                             or renders context itself.
    memory.py                Renders an already-retrieved Memory result
                             set into text. Never retrieves Memory.
    knowledge.py              Renders an already-retrieved Knowledge
                             result set into text. Never retrieves
                             Knowledge.
    context_builder.py        Calls Brain.assemble_context() (Context
                             Assembly) and renders the result via
                             memory.py/knowledge.py.
    session_context.py        Retrieves and renders saved-session
                             excerpts, only for an explicit past-
                             conversation request.
    capability_context.py     Discovers every enabled Capability from
                             CapabilityRegistry. No tool-spec or
                             schema knowledge.
    tool_context.py           Converts discovered Capabilities into
                             native tool-calling specs, composing each
                             Capability's own Tool Affordance Contract
                             into its advertised description, and
                             applies the two fixed-scope memory-
                             authorization gates -- reading every fact
                             generically from each Capability's own
                             metadata, never from a hardcoded
                             capability/tool list.
goal_builder.py            Builds the `Goal` handed to Brain, and
                              injects the Worker Model Inventory (see
                              `worker_inventory.py`) once Planner has
                              selected this Goal's own routing model.
    goal_decomposer.py         Decomposes high-level user requests into
                              multiple semantic Goals with dependencies.
    worker_inventory.py        Renders a compact, semantic inventory
                              of other installed AI models -- objective
                              provider facts kept strictly separate
                              from PARIKA's own observed Model
                              Knowledge (see `parika/core/semantics
                              /model_knowledge.py`). Never selects,
                              ranks, or filters a model itself.

Capability Independence (mandatory): no module in this package may
reference a specific Capability id, tool name, or affordance value by
name. Every Capability-specific fact (Tool Affordance Contract,
authorization requirements) must be read generically from
`CapabilityDefinition.metadata`, populated by that Capability's own
Tool/Module -- never defined or hardcoded here. See `tool_context.py`
and `docs/architecture/Request_Understanding.md` for the full
rationale and dependency direction:

    Capability -> Capability Metadata -> Tool Affordance Contract
        -> AI Context Engineering -> Prompt -> Brain

Security (Permission System, Policy Engine, Workspace/Filesystem/Shell
Scope, Authentication, Authorization) is never owned here and is never
touched by any module in this package.
"""

from __future__ import annotations
