# PARIKA Decision Flow

**Status:** Explains, in detail, how PARIKA thinks and decides what to do —
from a user request to a final response.

**Scope note (read this first):** This document distinguishes between two
things:

**Related documents:** [PARIKA_Architecture_Specification_v1.0.md](PARIKA_Architecture_Specification_v1.0.md) for the system boundary and [Core_Component_Responsibilities.md](Core_Component_Responsibilities.md) for the frozen component responsibilities.

- **Live, implemented behavior** — code that exists today in `parika/core/`
  and is exercised by the test suite (see [`../guides/Testing.md`](../guides/Testing.md)).
- **Architectural intent** — behavior the frozen architecture describes
  (e.g. Memory/Knowledge consultation, semantic goal decomposition from free
  text, multi-step Workflows) that is designed-for but not yet wired into
  the live `Brain`/`Planner` pipeline in this codebase.

Every section below is marked with an **Implementation Status** note so
this document never overstates what the code actually does today. This is
required by the project's own quality bar ("Documentation reflects the
actual implementation").

------------------------------------------------------------------------

# 1. The Pipeline, End to End

```text
User / Interface
       |
       v
   +--------+        (1) receives a BrainRequest carrying one or
   | Brain  |             more already-decomposed Goals
   +--------+
       |
       v
   +----------+       (2) orders Goals by dependency, resolves each
   | Planner  |            Goal's Capability, evaluates policy,
   +----------+            selects a Tool or Provider model
       |
       |  CapabilityResolver -> ResourceManager -> PolicyEngine -> ProviderManager/ToolManager
       v
  ExecutionPlan (ordered PlanStep[] of CapabilityExecutionRequest)
       |
       v
   +-------------+     (3) creates a Task per Goal, executes it
   | TaskManager |
   +-------------+
       |
       v
   +----------------------+   (4) measures duration, delegates to the
   | CapabilityExecutor    |       selected backend, wraps failures
   +----------------------+
       |
       +---------------------------+
       |                           |
       v                           v
   +-------------+           +-----------------+
   | ToolManager |           | ProviderManager |
   +-------------+           +-----------------+
       |                           |
       v                           v
   ToolDriver.execute()      ProviderDriver.execute()
   (e.g. Web Search Tool)    (e.g. an LLM provider)
       |                           |
       +-------------+-------------+
                     |
                     v
            Result flows back up:
   ToolResponse/ProviderResponse -> CapabilityExecutionResponse ->
   TaskResponse -> GoalResult -> BrainResponse -> User / Interface
```

Every arrow in this diagram is a real method call in the current codebase
except where the "Implementation Status" notes below say otherwise.

------------------------------------------------------------------------

# 2. Brain — Receiving the Request

**Responsible for:** receiving the request, coordinating every other Core
component, supervising execution across Goals, producing the final
response.

Brain's public API is a single method:

```python
Brain.handle(request: BrainRequest) -> BrainResponse
```

A `BrainRequest` carries a tuple of `Goal` objects. A `Goal` is the atomic
unit Planner and TaskManager operate on: a `capability_id`, `inputs`,
optional `depends_on` (other Goal ids in the same request), optional
`policy_rules`, and an optional `provider_request_builder` (needed only if
the Goal resolves to a Provider rather than a Tool).

**Why Brain never raises for pipeline failures:** Brain's job is to always
hand the caller *something* coherent. `handle()` catches every exception
from planning and execution and reports it inside the returned
`BrainResponse` (`planning_failure`, or a `GoalResult.failure`) rather than
propagating it. It only raises `InvalidBrainRequestError` for a
structurally malformed call (not a `BrainRequest` instance at all) — a
caller programming error, not a runtime condition.

**What Brain does next:** it calls `AgentOrchestrator.assign_agents_to_goals(request.goals)` to assign agents to Goals based on capability, specialization, and policy. Agent metadata (`agent_id`, `agent_specialization`, `agent_confidence`, `agent_reason`) is attached to each Goal's metadata. Then it calls `Planner.plan(request.goals)`. If that
raises, Brain wraps the exception into `BrainResponse(planning_failure=...)`
and returns immediately — no Task is ever created. If planning succeeds,
Brain supervises execution of the resulting `ExecutionPlan` (see §8).

**Execution progress (Phase 3.5b):** `Brain.__init__()` accepts an
optional `event_bus: EventBus | None = None` parameter. When supplied,
`handle()` self-publishes one `brain.execution` execution-progress tree
per call — `brain.execution.started/completed/failed` at the root
(`task_id=None`, since one request may span more than one Task), with a
`brain.planning` child wrapping the `Planner.plan()` call above and one
`brain.execute_goal` child per Goal (carrying that Goal's real
`TaskManager` `Task.id`) wrapping §8's execution supervision. This reuses
the existing, unmodified `ProgressReporter`/`ProgressEvent` mechanism
(`parika/core/utilities/progress.py`) — see that module and
`docs/architecture/Core_Component_Responsibilities.md` §5/§29. Omitting
`event_bus` leaves every other `handle()` behavior unchanged; it simply
reports nothing. The native PARIKA Console
(`parika/console/progress_view.py`) renders this tree live.

**Implementation Status:** Live. `Brain.handle()`, its planning-failure
capture, its execution supervision loop with dependency-aware concurrency
(§8.1), and its `brain.execution.*` progress reporting are all real,
tested code (`parika/core/brain/brain.py`).

------------------------------------------------------------------------

## 8.1 Multi-Agent Execution Supervision

`Brain._supervise_async()` executes `ExecutionPlan` steps with
dependency-aware concurrency:

1. **Agent Assignment:** Already completed in `Brain.handle()` via
   `AgentOrchestrator.assign_agents_to_goals()`.
2. **Dependency Graph:** Built from `ExecutionPlan.steps` using
   `PlanStep.depends_on`.
3. **Concurrent Execution:** Independent Goals (no dependencies) execute
   concurrently up to `[concurrency] max_concurrent_goals` (default 4).
   Dependent Goals wait for all required dependencies to complete
   successfully.
4. **Failure Propagation:** If a Goal fails, all dependent Goals are
   skipped with `skip_reason`. Unrelated Goals continue independently.
5. **Result Aggregation:** Results are collected in the original
   topological order for `BrainResponse`.

The concurrency limit is configured via `[concurrency] max_concurrent_goals`
(default: 4) in `config/defaults.toml`. Setting it to 1 preserves the
original sequential behavior.

------------------------------------------------------------------------

# 3. Goal Decomposition — Who Decides *What* To Do

Before Brain ever sees a request, something had to decide: *"this user
intent requires calling capability X with these inputs."* That is goal
decomposition.

**Why Planner does not do this itself:** semantic decomposition of free-form
human intent ("who is the president of India?") into a structured
`Goal(capability_id=..., inputs=...)` requires reasoning — usually an LLM
call. Planner's stated responsibilities are Dependency ordering and
Execution strategy, not reasoning; Brain's stated responsibilities include
"Maintain overall system intelligence" but Brain also explicitly does
**not** "Replace specialized Core components" — it doesn't itself contain an
LLM prompt loop.

**Implementation Status: architectural intent, not yet wired.** In the
current codebase, `Goal` objects are supplied to `Brain.handle()`
pre-decomposed by the caller. This is exactly the shape needed for the
concrete scenario this project targets today: an Ollama model doing
function/tool calling. When Ollama's chat API decides to call the
`web_search` function, its `tool_calls[0].function.arguments` **is**
already a fully decomposed, structured intent — `{"query": "...",
"max_results": 5}` — that maps directly onto
`Goal(capability_id="web.search", inputs=arguments)` with no additional
reasoning step required inside PARIKA. See §10 (Example A) and §11
(Example B) for exactly how this plays out, and
[`../guides/Running.md`](../guides/Running.md) §6 for the real, verified Ollama integration.

A future reasoning layer (a Module, or a dedicated capability, backed by an
LLM Provider) could decompose truly free-form multi-step intent into
multiple `Goal`s with `depends_on` relationships before calling
`Brain.handle()`. Nothing in the frozen architecture would need to change
to add this — it is exactly the kind of caller-supplied decomposition
Brain and Planner are already designed to accept.

------------------------------------------------------------------------

# 4. Planner — Turning Goals Into an Executable Plan

**Responsible for:** Goal decomposition *support* (dependency ordering of
already-decomposed Goals), Execution planning, Dependency ordering,
Execution strategy.

`Planner.plan(goals)` does exactly four things, in order, per Goal (after
validating and topologically sorting all Goals by `depends_on` up front):

### 4.1 Capability resolution

```python
resolution = capability_resolver.resolve(
    CapabilityRequest(capability_id=goal.capability_id, metadata=goal.metadata)
)
```

`CapabilityResolver` looks the capability up in `CapabilityRegistry`,
rejects it if disabled, and returns an immutable `CapabilityResolution`
wrapping the `CapabilityDefinition` (which carries `category`, e.g. `TOOL`
or `LLM`). **This is where "does this capability exist and is it enabled"
is decided** — nowhere else.

**Returns to Planner:** `CapabilityResolution`.
**Failure:** `CapabilityNotFoundError` / `CapabilityDisabledError` — these
propagate straight out of `plan()` (Planner does not swallow them);
Brain catches them and reports `planning_failure`.

### 4.2 Resource snapshot

```python
resource_snapshot = resource_manager.get_resource_snapshot()
```

Called once per `plan()` call (not once per Goal). Produces an immutable
`ResourceSnapshot` (CPU, memory, disk, GPU, network, filesystem). **This is
where current system resource state is captured** for policy rules to
consult — Planner itself does not threshold or interpret these numbers.

### 4.3 Policy evaluation

```python
decision = policy_engine.evaluate(
    PolicyEvaluationRequest(
        rules=goal.policy_rules,
        context={
            "goal_id": ..., "capability_id": ..., "capability_category": ...,
            "inputs": goal.inputs, "resource_snapshot": resource_snapshot,
        },
        default_effect=PolicyEffect.ALLOW,
    )
)
if not decision.is_allowed:
    raise GoalDeniedByPolicyError(...)
```

**This is where "is this Goal allowed to run right now" is decided.**
`PolicyEngine` is a stateless evaluator: it never stores policies. The
`PolicyRule`s it evaluates are supplied by the *caller that built the
Goal* — Planner only assembles the context (capability id/category,
inputs, resource snapshot) and asks PolicyEngine to resolve conflicts
between whichever rules were attached to that Goal. If a Goal carries no
rules, the default effect (`ALLOW`) wins and nothing is blocked — no
policy attached means no restriction.

**Implementation Status:** Live end-to-end, but note: PARIKA does not yet
ship a first-class "Policies" source that automatically attaches rules to
every Goal (e.g. a "no internet during quiet hours" rule loaded from
`Policies/` and applied to *every* Goal touching the `NETWORK` category).
Today, whoever constructs the `Goal` decides which `PolicyRule`s (if any)
apply to it. This matches the architecture ("Policies define behavior
instead of code") but the *automatic attachment* of the right rules to the
right Goals is a future Brain/Interface responsibility, not Planner's.

### 4.4 Execution strategy: Tool or Provider

```python
if resolution.definition.category is CapabilityCategory.TOOL:
    target, backend_request = self._select_tool(goal)
else:
    target, backend_request = self._select_provider_model(goal, resolution, category)
```

**This is where "which Tool, or which Provider + model" is decided.**

- **TOOL category:** Planner scans `tool_manager.get_all()` for an
  **enabled** `Tool` whose `capabilities` tuple contains the requested
  capability id, sorted deterministically by tool id, and picks the first
  match. No enabled Tool → `NoAvailableToolError`.
- **Non-TOOL category (LLM, VISION, EMBEDDING, TRANSLATION, SPEECH,
  REASONING, PLANNING):** Planner maps the `CapabilityCategory` to a
  required `ModelCapability` and builds a provider-independent
  `ExecutionRequirements` for the Goal
  (`build_execution_requirements()`). This includes a **Task
  Classification** step - a small, generic `CapabilityCategory ->
  TaskCategory` derivation (e.g. `LLM` -> `general_chat`, `VISION` ->
  `vision_understanding`) whose resulting `TaskRequirementProfile`
  supplies default `required_specializations`/`required_capabilities`/
  `required_modalities`/`required_execution_features` - and an explicit
  `Goal.metadata["execution_requirements"]` override supplied by a
  caller (e.g. AI Context Engineering), which may set `tool_calling`
  (`REQUIRED`/`PREFERRED`/`NOT_NEEDED`), `information_freshness`,
  strongly-typed `capability_hints`, an explicit `task_category`, or any
  other requirement field directly - Planner's former text-based
  Requirement Inference framework, which used to derive these same
  fields from `Goal.inputs["message"]` via pattern/regex rules, has been
  removed (see [`Request_Understanding.md`](Request_Understanding.md)).
  Planner then delegates to the Intelligent Model Selection Framework
  ([`Model_Selection_Framework.md`](Model_Selection_Framework.md)):
  every enabled, available Provider's models are first **filtered** -
  by specialization, required capabilities/execution features,
  modalities, provider health, provider availability, context window,
  and declared resource requirements, in that order, each with a
  specific rejection reason - and only the surviving candidates are
  **ranked** against `[model_selection]` configuration, with the
  highest-scoring match winning (deterministic tie-break by
  provider/model id). Ranking never gets a chance to let an unsuitable
  candidate win: a `tool_calling` requirement of `REQUIRED`, or a task's
  required specialization/capability/modality, excludes a non-matching
  model *before* scoring even runs - this is both how a message like
  *"What is the current time in IST?"* is routed to a tool-capable model
  instead of being answered directly by an LLM that would otherwise
  hallucinate or guess, and how an OCR- or embedding-specialized model
  is kept out of an ordinary chat request's candidate pool once a
  Provider advertises that specialization. Ranking may also be
  influenced by an AI-assisted **routing recommendation** - a ranked
  list of candidate `(provider_id, model_id, confidence)` the routing
  model itself supplied for this specific request (via the reserved
  `model_selection_hint` tool-call argument, forwarded through
  `Goal.metadata["execution_requirements"]["metadata"]
  ["candidate_models"]` exactly like any other override, and scored by
  one more `ScoringRule`, `RoutingRecommendationRule`) - see
  [`Model_Selection_Framework.md`](Model_Selection_Framework.md) §6.3/
  §13. This is purely one more scoring signal: it can never select a
  candidate the filtering step above already rejected, and a request
  carrying no such recommendation scores identically to before this
  existed. **For the routing Goal specifically** (the Goal marked
  `Goal.metadata[ROUTING_GOAL_METADATA_KEY]`, set only by
  `goal_builder.build_chat_goal()`), Planner may instead skip this
  entire ranking step and use one operator-pinned model directly, when
  `[routing_model] mode = "fixed"` is configured - a latency
  optimization for the routing decision only; worker Goal selection is
  unaffected, filtering is never skipped even for a pinned model, an
  unavailable pinned model logs a warning and falls back to the ranking
  step just described, and the default (`mode = "auto"`) is unchanged
  from today - see
  [`Model_Selection_Framework.md`](Model_Selection_Framework.md) §14.
  No match →
  `NoAvailableProviderModelError`. The caller must also have supplied a
  `provider_request_builder` on the Goal — Planner cannot construct a
  concrete, provider-specific request payload itself, so a missing
  builder raises `MissingProviderRequestBuilderError`. Planner also
  resolves a generic `RequestOptions.reasoning` ("thinking") preference
  from the selection decision and applies it onto whatever
  `ProviderRequest` the builder returned; translating that preference
  into a concrete provider mechanism (e.g. Ollama's `think` field) is
  left entirely to the Provider. None of this performs semantic
  decomposition of the request into multiple Goals: every override and
  Task Classification default only ever enriches the requirements of
  the one Goal Planner already has.

  **Runtime Context Budget:** immediately after a model is selected,
  Planner also computes this request's Runtime Context Budget
  (`provider_manager.context_budget.resolve_runtime_context_budget()`)
  from the selected model's own advertised `ModelLimits.context_window`
  (Model Capabilities — the single source of truth) narrowed by the
  `[context_engine]` configuration ceiling, minus the configured
  reserved-for-response and safety-reserve token counts, and applies
  the resulting effective context window onto the built
  `ProviderRequest`'s generic `RequestOptions.context_window_tokens`
  field — the same "apply a generic preference onto whatever
  `ProviderRequest` the builder returned" pattern already used for
  `reasoning` above. This is never hardcoded: every value comes from
  the selected `ProviderModel` or from `[context_engine]`
  configuration. AI Context Engineering and Brain never learn a
  provider or provider-specific parameter exists; only the Provider
  that ultimately receives `RequestOptions.context_window_tokens`
  translates it into its own concrete request parameter (e.g. Ollama's
  `num_ctx`), preventing the model's effective context window from
  silently falling back to a Provider's own tiny default and
  truncating the Assistant Identity/Behavior/Reasoning
  Policy/Memory/Knowledge/Tool Affordance content already assembled
  into the prompt.

  The `[context_engine]` configuration ceiling on its own is a
  *default*, not an unconditional cap: `resolve_runtime_context_budget()`
  also accepts an optional `required_prompt_tokens` — the complete,
  already-assembled prompt's own measured token size for *this*
  request, read by Planner (`read_estimated_prompt_tokens()`) from the
  built `ProviderRequest`'s generic `RequestOptions
  .estimated_prompt_tokens` field. That field is set by AI Context
  Engineering's Prompt Engineering responsibility
  (`interfaces/ai_context/goal_builder.py`), which measures the one,
  final, already-fully-assembled prompt exactly once — using the same
  `TokenEstimator` infrastructure Brain's own Context Budgeting already
  uses — immediately after every prompt-contributing ingredient
  (Assistant Identity, Behavior, Constraints, Reasoning Policy, Model
  Selection Policy, Worker Inventory, Tool Descriptions, Conversation,
  Memory, Knowledge) has already been folded into it, never by summing
  those ingredients' estimates individually. When supplied, the
  effective context window grows just enough to cover that measured
  size, still never exceeding the selected model's own true
  `context_window` when known, and never inflated by an arbitrary
  buffer. `RequestOptions.estimated_prompt_tokens` being `None` (a
  Provider request with no prompt concept at all, such as a future
  ComfyUI workflow or Whisper transcription request) reproduces the
  behavior above exactly. Planner and ProviderManager never measure a
  prompt themselves, and never learn what a message or a tool schema
  is; they only ever read an already-supplied, provider-independent
  token count.

The result is one `ExecutionTarget` (backend + identifier + optional
model) and one opaque `backend_request` (`ToolRequest` or a
provider-specific `ProviderRequest`), wrapped into a
`CapabilityExecutionRequest` together with the `CapabilityResolution`.

**Returns from `plan()`:** an immutable `ExecutionPlan` — a
dependency-ordered tuple of `PlanStep(goal_id, execution_request,
depends_on)`. Planner never executes anything; it hands this plan back to
Brain.

**Implementation Status:** Live and fully tested
(`tests/core/planner/test_planner.py`,
`tests/core/planner/test_planner_model_selection.py`,
`tests/core/planner/model_selection/`), including every failure path
above and the Intelligent Model Selection Framework's scoring,
filtering, and transparency logging. Planner's former Requirement
Inference framework (message-based `tool_calling`/
`information_freshness` derivation via regex) has been removed as
part of the AI Context Engineering migration - see
[`Request_Understanding.md`](Request_Understanding.md); the AI
Context Engineering layer now supplies an explicit
`Goal.metadata["execution_requirements"]` override instead. Verified
end to end against a real Ollama instance: a `"What is the current
time in IST?"` request is correctly routed to a tool-calling-capable
model that calls the real system clock, instead of an LLM guessing.

------------------------------------------------------------------------

# 5. Router — Where It Fits (and Where It Doesn't, Yet)

**Responsible for:** routing a validated request to the appropriate
execution path, based on a registered `matcher` predicate per `Route`.

**Implementation Status: implemented and tested, but not currently invoked
by Brain.** Brain's current pipeline always goes `Planner → TaskManager`
for every Goal; there is currently only one execution path (Task-based
execution through `CapabilityExecutor`), so there is nothing for Router to
choose between yet. Router becomes relevant once a second execution path
exists to route between — the most natural candidate is choosing between
`TaskManager` (single-capability Goals, today's only path) and
`WorkflowEngine` (multi-step Workflows, not yet execution-complete — see
§9) based on whatever shape the incoming request takes. Router's
`select()`/`dispatch()` API is ready for that day without any changes.

------------------------------------------------------------------------

# 6. TaskManager — Coordinating Execution

**Responsible for:** Task creation, lifecycle (pending → running →
completed/failed), pause/resume/cancel/retry, and delegating the actual
work to `CapabilityExecutor`.

For each `PlanStep`, in the dependency order Planner already computed,
Brain does:

```python
task = task_manager.create(TaskRequest(
    capability_id=goal.capability_id, inputs=goal.inputs,
    context_id=goal.context_id, metadata=goal.metadata,
))
executed_task = task_manager.execute(task.id, step.execution_request)
```

`create()` is bookkeeping only — it registers a `Task(status=PENDING)` and
publishes `task.created`. `execute()` is where the real work happens:

1. Guards the Task's current status (raises `TaskAlreadyRunningError` /
   `TaskAlreadyCompletedError` / `TaskCancelledError` / `TaskPausedError`
   if it isn't `PENDING`/`WAITING`).
2. Transitions to `RUNNING`, publishes `task.started`.
3. Calls `CapabilityExecutor.execute(step.execution_request)` — this is
   the **only** place TaskManager talks to CapabilityExecutor. TaskManager
   never resolves capabilities, never selects a backend, and never
   inspects the *contents* of whatever comes back (`backend_response` is
   stored completely opaquely under `TaskResponse.outputs["result"]`).
4. On success: `COMPLETED`, `task.completed` event, returns the `Task`
   (with `.response` populated).
5. On failure: `FAILED`, `task.failed` event, raises `TaskExecutionError`
   chained (`__cause__`) to whatever `CapabilityExecutor` raised.

**Retry:** `TaskManager.retry(task_id, execution_request)` is only valid
from `FAILED`. It increments `task.metadata["retry_count"]`, resets status
to `PENDING`, and re-invokes `execute()` — i.e. retry is a full re-run of
the same (or a newly supplied) `CapabilityExecutionRequest`, not a partial
resume. Brain itself does not automatically call `retry()` today; a Task
that fails during Brain's supervision loop is reported as failed in the
`GoalResult`, and any dependent Goals are skipped (§8). Retrying is
available for a caller (or a future Brain enhancement) to invoke
explicitly.

**Implementation Status:** Live, fully tested
(`tests/core/task_manager/test_task_manager.py`).

------------------------------------------------------------------------

# 7. CapabilityExecutor — Delegating to the Backend

**Responsible for:** validating the execution request, measuring duration,
delegating to `ToolManager` or `ProviderManager` based on
`execution_request.target.backend`, publishing execution events, and
wrapping backend failures into `CapabilityExecutionError`.

```python
if target.backend is ExecutionBackend.TOOL:
    backend_response = tool_manager.execute(tool_id=target.identifier, request=backend_request)
else:  # ExecutionBackend.PROVIDER
    backend_response = provider_manager.execute(provider_id=target.identifier, model=target.model, request=backend_request)
```

CapabilityExecutor does not know or care *what* the Tool or Provider does
internally — `ToolResponse`/`ProviderResponse` are opaque to it too. It
publishes `capability.execution.started`/`.completed`/`.failed` and
returns an immutable `CapabilityExecutionResponse(backend_response,
metadata, duration_seconds)` up to TaskManager.

`execute()` accepts an optional `task_id: str | None = None` (Phase
3.5b), forwarded unchanged onto all three published events.
`TaskManager.execute()` (§6) passes its own real `Task.id`, so a
subscriber can correlate one execution's Started event to its own
Completed/Failed counterpart and to the owning Task — `None` when
`execute()` is called without one.

**Implementation Status:** Live.

------------------------------------------------------------------------

# 8. ToolManager / ProviderManager — The Actual Work

**ToolManager.execute(tool_id, request)** looks up the registered `Tool`
and its `ToolDriver`, calls `driver.execute(request)`, validates the
returned type is a `ToolResponse`, publishes `tool.executed` /
`tool.execution_failed`, and wraps any driver exception in
`ToolExecutionError`. This is where, for example, the Web Search Tool's
`WebSearchToolDriver.execute()` actually runs (see
[`../development/Tool_Guide.md`](../development/Tool_Guide.md) for its
internals: search, retry, timeout, page fetch, and text extraction all
happen inside this one driver call).

**ProviderManager.execute(provider_id, model, request)** looks up the
registered `Provider`, calls its `ProviderDriver.execute(model, request)`,
and returns whatever `ProviderResponse` the driver produces. Unlike
`ToolManager`, `ProviderManager.execute()` does **not** wrap driver
exceptions — they propagate unwrapped (documented, verified by test; see
`tests/core/provider_manager/`). This is a real, current asymmetry between
the two managers.

**Implementation Status:** Both managers and their delegation are fully
live. As of this milestone, a production `ProviderDriver` implementation
ships in this repository: `OllamaProviderDriver`
(`parika/providers/ollama/`), registered by default via
`build_default_runtime()` (`parika/interfaces/runtime.py`). It supports
model discovery, health checks, streamed and non-streamed generation and
chat, and native tool calling resolved by calling `Brain.handle()` (see
section 12 below and `Running.md` section 8.3). The Web Search Tool and
the Ollama provider are both fully production-ready backends today.

A dedicated backend stabilization milestone subsequently hardened and
exhaustively validated this native tool-calling path - see
[`Provider_Tool_Calling.md`](Provider_Tool_Calling.md): a generic (never
capability-specific) fallback recovers a tool call even when a model's
own chat template leaks it as plain text instead of Ollama's native
`tool_calls` field, and a bounded retry recovers a genuinely blank final
answer. Neither `ProviderManager` nor `Planner`'s selection logic needed
any change - the bottleneck was entirely inside Provider-level response
parsing.

## 8.1 A second Provider: ComfyUI (image/video generation)

A second production `ProviderDriver` ships in this repository:
`ComfyUIProviderDriver` (`parika/providers/comfyui/`), registered by
default via `build_default_runtime()`/`_register_comfyui_provider()`
alongside Ollama. It satisfies the generic `ProviderDriver` contract
exactly like Ollama does — `discover_models()`, `check_health()`,
`execute(model, request)` — proving the contract genuinely
generalizes beyond chat-shaped providers:

- **Request/response types:** a new pair of provider-independent
  types was added to `parika/core/provider_manager/` following the
  same pattern as `ChatRequest`/`ChatResult`: `GenerationRequest`
  (an `operation: GenerationOperation`, a text `prompt`/
  `negative_prompt`, optional `input_images` (base64, same shape as
  `ChatMessage.images`), optional `width`/`height`/
  `duration_seconds`/`fps`/`seed`) and `GenerationResult` (a tuple of
  `GeneratedArtifact { content_base64, mime_type }`). Neither type
  mentions ComfyUI, a workflow graph, a node id, a checkpoint, a
  sampler, or a queue id — exactly the same discipline `ChatRequest`
  already established for Ollama's own wire format.
- **Model discovery:** `GET /models/diffusion_models` against the
  live ComfyUI server is authoritative for the image model and for
  any video model configured with `video_t2v_loader`/
  `video_vace_loader = "native"` (see the loader bullet below).
  `ComfyUIModelConfig` names which diffusion-model/text-encoder/VAE
  filenames this provider is configured to use (`[providers.comfyui]`
  in `config/defaults.toml`); a configured model that is not actually
  installed is simply not offered as a candidate to Model Selection,
  mirroring Ollama's own "the installed environment is authoritative"
  discovery behavior. A video model configured with `loader = "gguf"`
  is instead checked against `GET /models/unet_gguf` — ComfyUI-GGUF
  (see the loader bullet below) registers `.gguf` checkpoints under
  that distinct folder listing rather than `diffusion_models` — fetched
  only when at least one video model is actually configured with
  `loader = "gguf"`, so a native-only installation makes exactly the
  one discovery request it always has. If that additional listing
  cannot be fetched (e.g. ComfyUI-GGUF is not installed), the
  GGUF-configured model is simply treated as not installed, exactly
  like an uninstalled checkpoint file — it does not prevent discovery
  of every other model. See `discovery.model_listing_path_for_loader()`.
- **Video model loading precision:** for the two video models, the
  diffusion-model filename (`video_t2v_diffusion_model`/
  `video_vace_diffusion_model`) and the `UNETLoader` loading
  precision ComfyUI actually loads it at (`video_t2v_weight_dtype`/
  `video_vace_weight_dtype`) are deliberately independent
  `ComfyUIModelConfig` fields — the dtype is never inferred from the
  filename. Supported values are ComfyUI's own native `UNETLoader`
  choices: `"default"`, `"fp8_e4m3fn"`, `"fp8_e4m3fn_fast"`,
  `"fp8_e5m2"`. Omitting either dtype key preserves the previous
  behavior (`weight_dtype = "default"`), so a configuration using the
  original `video_vace_diffusion_model =
  "wan2.1_vace_1.3B_fp16.safetensors"` with no dtype key keeps
  working unchanged. `config/defaults.toml` currently configures the
  low-VRAM `video_vace_diffusion_model =
  "wan2.1_vace_1.3B_fp8_scaled.safetensors"` with
  `video_vace_weight_dtype = "fp8_e4m3fn"`; switching to that FP16
  checkpoint (`weight_dtype = "default"`), or to any other Wan/VACE
  checkpoint the existing `WanVaceToVideo` workflow already supports,
  is purely a configuration change through the normal configuration
  layers/precedence (see `docs/guides/Running.md`) — no code change
  is required either way.
- **Video model loading backend (native/GGUF):** which ComfyUI node
  actually loads a video diffusion model is a third `ComfyUIModelConfig`
  field, independent of both the filename and the `weight_dtype` above
  — `video_t2v_loader`/`video_vace_loader`, one of `"native"`
  (ComfyUI's own `UNETLoader`, today's only behavior) or `"gguf"` (the
  `ComfyUI-GGUF` custom node's `UnetLoaderGGUF` —
  https://github.com/city96/ComfyUI-GGUF — required for
  `.gguf`-quantized checkpoints, which `UNETLoader` cannot load).
  Neither loader is ever inferred from the filename's extension: a
  `.gguf` file configured with `loader = "native"` (or vice versa) is
  not silently corrected — `ComfyUIModelConfig.__post_init__` rejects
  an unrecognized `loader` value outright, and separately rejects any
  `weight_dtype` other than `"default"` whenever `loader = "gguf"`
  (`UnetLoaderGGUF` has no `weight_dtype` input; a GGUF checkpoint's
  quantization is already fixed by the file itself).
  `workflows._diffusion_model_loader_node()` is the only place either
  loader's ComfyUI node type is named, and it is selected purely by
  this configuration value, never by the filename. If the loader
  itself is unavailable in the running ComfyUI installation (e.g.
  ComfyUI-GGUF is not installed, so `UnetLoaderGGUF` does not exist as
  a node type), submitting a workflow built with `loader = "gguf"`
  fails clearly and immediately: ComfyUI's `POST /prompt` response
  includes `node_errors` for the unrecognized node type, which this
  provider already surfaces as `ComfyUIWorkflowError` — no fallback to
  another loader is attempted. `config/defaults.toml` documents the
  installed Q4_K_M GGUF VACE checkpoint
  (`wan2.1-vace-1.3b-q4_k_m.gguf`) as a commented `loader = "gguf"`
  alternative to the active native FP8 configuration; switching to it
  (and back) is purely a configuration change, verified end-to-end
  against a live ComfyUI 0.31.1 + ComfyUI-GGUF installation during
  development — no code change either way. Prerequisites: the
  ComfyUI-GGUF custom node package installed, its `gguf` Python
  dependency installed in ComfyUI's own environment, and the `.gguf`
  file placed in ComfyUI's `models/unet/` directory.
- **Workflow construction:** entirely inside `providers/comfyui/
  workflows.py`. Core and every Module never see a ComfyUI node graph;
  they build a `GenerationRequest`, and the selected Provider translates
  it into a concrete `POST /prompt` payload, polls
  `GET /history/{prompt_id}`, and retrieves the produced artifact via
  `GET /view`.
- **Capability routing:** two new `CapabilityCategory` members were
  added — `IMAGE_GENERATION` and `VIDEO_GENERATION` — each mapped to
  the corresponding pre-existing `ModelCapability` in `Planner`'s
  `CATEGORY_TO_MODEL_CAPABILITY` table (§4.4), and to the pre-existing
  `TaskCategory.IMAGE_GENERATION`/`VIDEO_GENERATION` in
  `task_classification.py`'s `_CATEGORY_TASK_DEFAULTS`. Every other
  requirement dimension needed by `image.edit`/
  `video.generate_from_image`/`video.edit` (which share a
  `CapabilityCategory` with `image.generate`/`video.generate` but need
  a *different* model) is expressed entirely through the pre-existing
  `Goal.metadata["execution_requirements"]["task_category"]` override
  mechanism — no Planner code change was required for that
  distinction.
- **Consuming capabilities:** `image.generate`, `image.edit`,
  `video.generate`, `video.generate_from_image`, and `video.edit`
  (`parika/modules/generation/`) follow the exact TOOL-Capability +
  internal-Provider-Capability shape every other hybrid Module
  Capability already uses (see `vision.remove_background`'s own
  shape in §4.4) — a Tool orchestrator reads/writes files through the
  existing Filesystem Capability and reaches the Provider only through
  a nested `Goal`, resolved by the same, unmodified Planner/Model
  Selection Framework.
- **Existing `vision.remove_background`/`vision.enhance_image`:**
  investigated and deliberately left unchanged. Both remain
  deterministic-only (OpenCV GrabCut / Pillow enhancement); ComfyUI
  was not wired as an alternative or fallback provider for either,
  because the installed ComfyUI instance has no background-removal or
  upscale model files installed (`models/background_removal/` and
  `models/upscale_models/` are both empty) — see the project's final
  implementation report for the full investigation and the concrete
  models that would need to be installed before this would become
  appropriate.

------------------------------------------------------------------------

# 9. Brain's Execution Supervision — Dependencies and Best Effort

Back in `Brain._supervise()`, for every `PlanStep` in the plan's
already-dependency-ordered sequence:

```text
if any of step.depends_on already failed:
    -> GoalResult(skipped=True, skip_reason="...")   # never creates a Task
else:
    -> create + execute the Task (§6)
    -> GoalResult(status=task.status, response=task.response, failure=...)
    if not succeeded:
        mark this goal's id as failed, so dependents get skipped too
```

This means: independent Goals in the same request always get a real
attempt, even if a sibling Goal fails (best-effort); a Goal that depends on
a failed Goal is never attempted at all (fail-fast for that branch only).
`BrainResponse.succeeded` is `True` only if every Goal in the request
`succeeded` (not skipped, status `COMPLETED`, no failure).

**Implementation Status:** Live
(`tests/core/brain/test_brain.py::TestExecutionFailureAndSkipping`).

------------------------------------------------------------------------

# 10. Where WorkflowEngine, Scheduler, MemoryManager, KnowledgeManager, and ContextManager Fit

None of these five components are called by Brain or Planner today. Each
is a complete, independently tested Core component available for a Module
or a future Brain enhancement to use:

- **WorkflowEngine** — for genuinely multi-step, stateful Workflows with
  pause/resume semantics beyond what a flat, dependency-ordered `Goal` list
  can express. As noted in §5/§9 of
  [`Core_Component_Responsibilities.md`](Core_Component_Responsibilities.md),
  its step-execution engine is not yet implemented, so it is not
  production-ready for real multi-step execution regardless of whether
  Brain called it.
- **Scheduler** — for time-based triggers (delayed or recurring jobs), e.g.
  a Module that wants to re-run a Task every hour. Independent of the
  request/response pipeline described above; nothing in §1–§9 depends on
  it.
- **MemoryManager** — for persisting immutable memory records (e.g. "the
  user prefers metric units"). A future decomposition/reasoning layer
  (§3) would be the natural place to *consult* Memory before building
  Goals, and to *write* new memories after a response is produced. Brain
  does not do either automatically today. `InterfaceSession`'s Context
  Assembly (outside Brain/Planner) already calls `MemoryManager.search()`
  before every chat turn; that call now self-reports
  `memory.search.started/completed/failed` progress (Phase 3.5b) through
  `MemoryManager`'s own already-injected `EventBus`, observed live by the
  Console and captured into `InterfaceSession.LastTurnDiagnostics
  .progress_trail`.
- **KnowledgeManager** — for indexing/searching locally-held knowledge
  sources. Same story as Memory: a future reasoning layer would check
  "can Knowledge answer this without a live web search" before building a
  `web.search` Goal. Not wired into Planner/Brain today. Its `search()`
  self-reports `knowledge.search.*` progress the same way (Phase 3.5b),
  under the same conditions as MemoryManager above.
- **ContextManager** — for registering transient runtime `Context` objects
  that a `Goal.context_id` can reference. `Goal` and `TaskRequest` both
  already carry an optional `context_id` field for exactly this purpose;
  Planner and TaskManager pass it through unchanged, but neither of them
  calls `ContextManager` to create, validate, or look up the Context
  itself — that remains the caller's/Interface's responsibility, matching
  ContextManager's explicit "Does NOT: Create contexts" boundary.

------------------------------------------------------------------------

# 11. Example A: "Who is the President of India?"

### Step by step

1. **Brain receives the request.** In today's implementation this means a
   caller has already built a `BrainRequest`. For a plain factual
   question with no tool call, the natural shape (once a reasoning layer
   exists — see §3) is a single Goal targeting an LLM capability:
   `Goal(id="q1", capability_id="chat.answer", inputs={"question": "Who is
   the President of India?"}, provider_request_builder=<builds a concrete
   chat request>)`.

2. **Goal creation / decomposition.** This is a single, atomic intent — no
   decomposition into sub-goals is needed. **Implementation Status:** the
   decision that this question needs *no* decomposition is made by
   whatever constructs the Goal (§3), not by Planner.

3. **Planner decomposition:** trivial — one Goal, no `depends_on`, nothing
   to topologically sort.

4. **Capability resolution:** `CapabilityResolver` resolves
   `"chat.answer"` (or whatever capability id a real deployment registers
   for general Q&A) against `CapabilityRegistry`. Suppose its
   `CapabilityDefinition.category` is `CapabilityCategory.LLM`.

5. **Is internet needed?** No capability-level flag says "needs
   internet" explicitly in the current data model — this is decided
   *implicitly* by which backend the category resolves to. `LLM` category
   → PROVIDER backend (§4.4) → a model's own trained knowledge answers the
   question locally (or via whatever the Provider's own network transport
   is, if it's a hosted API) — **no Tool, no live web search, is
   selected**, because the Goal's capability was never `TOOL`-categorized
   in the first place.

6. **Could Memory or Knowledge answer this instead?** Conceptually, if
   this exact question had been asked and stored before, MemoryManager
   *could* short-circuit the whole pipeline. **Implementation Status:**
   not wired today (§10) — every request goes through the full pipeline
   regardless of whether the answer is "already known."

7. **Is a Tool required?** No — the resolved category is `LLM`, not
   `TOOL`, so Planner's `_select_provider_model()` path runs, never
   `_select_tool()`.

8. **Is a Provider required?** Yes. Planner scans registered, enabled
   Providers for one exposing a Model with `ModelCapability.TEXT_GENERATION`
   (the mapping for `LLM` — see §4.4), preferring a `CONNECTED` provider.

9. **Which capability, module, tool selected?** Capability = `chat.answer`
   (category `LLM`); no Module or Tool is involved at all for this
   example — this is the PROVIDER path, not the TOOL path.

10. **Why that selection happened:** because the capability's category maps
    to a Provider-satisfiable `ModelCapability`, and at least one enabled
    Provider+Model advertises it. If none did, Planner would raise
    `NoAvailableProviderModelError` and Brain would report a planning
    failure — the user would get "I can't currently answer that" rather
    than a wrong/silent answer.

11. **Execution path:** `Brain → TaskManager.create/execute →
    CapabilityExecutor.execute → ProviderManager.execute(provider_id,
    model, request) → ProviderDriver.execute(model, request) →
    ProviderResponse`. This flows back up unopened through
    `CapabilityExecutionResponse.backend_response` →
    `TaskResponse.outputs["result"]` → `GoalResult.response` →
    `BrainResponse`.

12. **Final response generation:** whatever the Provider's response text
    is, exactly as produced — Brain does not paraphrase, summarize, or
    add citations for a single-Provider-call answer; that formatting
    responsibility belongs to whatever built the
    `provider_request_builder`/consumes the final `BrainResponse` (an
    Interface layer), not to Brain itself ("Does NOT: Replace specialized
    Core components").

### Flow diagram

```text
"Who is the President of India?"
        |
        v
   Goal(capability_id="chat.answer", category=LLM)
        |
        v
   Planner.plan()
        |-- CapabilityResolver.resolve() -> category=LLM
        |-- ResourceManager.get_resource_snapshot()
        |-- PolicyEngine.evaluate()      -> ALLOW (no rules attached)
        |-- select_provider_model()      -> Provider X, Model Y (TEXT_GENERATION)
        v
   ExecutionPlan[ PlanStep(target=PROVIDER, model=Y) ]
        |
        v
   TaskManager.create()+execute()
        |
        v
   CapabilityExecutor.execute()
        |
        v
   ProviderManager.execute(provider=X, model=Y)
        |
        v
   ProviderDriver.execute(model=Y, request) -> ProviderResponse
        |
        v
   (unwrapped back up through every layer)
        |
        v
   BrainResponse.results[0].response  ->  final answer text
```

------------------------------------------------------------------------

# 12. Example B: "When was the last protest held in India, what was it about, who organized it, and what was the outcome?"

### Why this requires current information

The answer depends on a specific, recent, real-world event. No amount of a
model's own training data reliably has "the latest" instance of this — it
is fundamentally a *live* information-retrieval question, not a
general-knowledge one. This is the deciding factor for capability
selection: the underlying capability must be `TOOL`-categorized
(`web.search`), not `LLM`-categorized.

### How Brain recognizes this

**Implementation Status:** today, *recognizing* that a question needs live
information (vs. general knowledge) is exactly the decomposition step
described in §3 — it happens before `Brain.handle()` is ever called. In
the concrete, verified integration this project ships
([`../guides/Running.md`](../guides/Running.md) §6), that recognition is made by the Ollama
model itself via tool-calling: the model decides to emit a `web_search`
tool call rather than answering directly, precisely because it recognizes
the question needs current information it doesn't have. PARIKA does not
need to re-derive that decision — it receives it already made, as a
structured tool call.

### How Planner builds the execution plan

The tool call's arguments become `Goal(capability_id="web.search",
inputs={"query": "...", "max_results": 5})`. This single compound
question (when/what/who/outcome) is intentionally left as **one search
query** at the Goal level — decomposing "when was X, what was it about, who
organized it, what was the outcome" into four separate sub-goals is a
*reasoning* decision (again, §3's caller-decomposition responsibility, not
Planner's). Planner's part starts once Goals already exist:

1. `CapabilityResolver.resolve("web.search")` → category `TOOL`.
2. `ResourceManager.get_resource_snapshot()` — captured in case a policy
   rule cares (e.g. "no network if disk is critically full").
3. `PolicyEngine.evaluate(...)` — e.g. a rule like "deny network capabilities
   when `resource_snapshot.network.status is UNAVAILABLE`" could be attached
   to this Goal by its caller; if none is attached, `ALLOW` by default.
4. `_select_tool()` scans `ToolManager` for an enabled Tool whose
   `capabilities` includes `"web.search"` → the Web Search Tool
   (`tool.web_search`).

### Why a Web Search capability, and which Module/Tool owns it

`web.search` is registered by the Web Search **Module**
(`parika/modules/web_search/`) when it is loaded — its `ModuleDriver`
registers the `CapabilityDefinition` with `CapabilityRegistry` and the
`Tool` (plus its `WebSearchToolDriver`) with `ToolManager` (see
[`../development/Module_Guide.md`](../development/Module_Guide.md) §4).
The Module owns the capability's existence; the Tool owns the
capability's execution.

### Whether multiple searches are performed

Within a single `web.search` call, `WebSearchToolDriver.execute()`
performs exactly one query against the configured `SearchBackend` -
`GoogleHtmlSearchBackend` by default (see
`parika/tools/web_search/config.py`'s `DEFAULT_PROVIDER`), or a
`FailoverSearchBackend` spanning every provider configured in
`[web_search].provider_order` once `config/defaults.toml` is loaded
(see `Tool_Guide.md` §18) - returning up to `max_results` results
(default 5), each with `title`/`url`/`snippet`. If
`include_content=True` is set in the Goal's `inputs`, the driver then
fetches and extracts the full text of *each* result page via
`PageFetcher` — this is "multiple network calls" (one search + N page
fetches), all within the same single Task/Goal, not multiple separate
Goals. Whether a second, refined search is needed (e.g. the first query
returned nothing about *organizers*) is, again, a reasoning decision: a
model consuming the first `BrainResponse` could decide to issue a second
`web_search` tool call with a refined query, producing a second, entirely
independent Goal/Task cycle through the same pipeline.

### How results are validated

PARIKA's pipeline performs only structural/transport validation, never
content validation:

- `WebSearchToolDriver` validates `query` is present and non-empty
  (`InvalidSearchQueryError` otherwise).
- Every `search_backend_<provider>.py` backend retries transient network
  failures/timeouts (linear backoff, configurable attempts — see
  [`../development/Tool_Guide.md`](../development/Tool_Guide.md) §18) and
  raises a clear `WebSearchNetworkError` if
  the provider returns an anti-bot/CAPTCHA challenge page or an HTTP error
  instead of real results (detected explicitly, not silently treated as
  "zero results"). `FailoverSearchBackend` falls over to the next
  configured provider on any such failure (see `Tool_Guide.md` §18).
- `ToolManager.execute()` validates the driver returned an actual
  `ToolResponse`, not some other type.

**Nothing in this pipeline judges whether the search *results themselves*
are accurate, complete, or trustworthy.** That is squarely the
"interpret execution results" responsibility Brain, TaskManager, and
CapabilityExecutor all explicitly do **not** own. Content
validation/synthesis, if PARIKA is to have it, belongs to a future
reasoning layer consuming the raw `BrainResponse.results[0].response`.

### How information is synthesized and citations are produced

**Implementation Status: not implemented today.** The current pipeline's
final output for this example is the raw tool result:

```python
response.results[0].response.outputs["result"]  # a ToolResponse
# .result -> tuple[dict, ...] of {"title", "url", "snippet", "page"?}
# .attributes -> {"query": "...", "result_count": N}
```

Turning that list of titles/URLs/snippets into a synthesized natural-
language answer with citations ("According to [Source], the protest on
[date] was about X, organized by Y — see [url]") is exactly the kind of
step that requires an LLM Provider call over the search results — i.e. a
**second** Goal in the same request, depending on the first:

```python
goals = (
    Goal(id="search", capability_id="web.search", inputs={"query": "..."}),
    Goal(id="synthesize", capability_id="chat.answer",
         inputs={"context": "<results from 'search' inserted here>"},
         depends_on=("search",),
         provider_request_builder=...),
)
```

This two-Goal shape is fully supported by Planner's dependency ordering
and Brain's fail-fast-per-branch supervision (§9) today — Planner would
execute `search` first, and only attempt `synthesize` if `search`
succeeded. What is *not* implemented is the glue that automatically takes
`search`'s raw `ToolResponse` and threads it into `synthesize`'s
`inputs["context"]` — that data-flow-between-Goals wiring is currently the
caller's responsibility (the same reasoning layer from §3), not
Planner's, since Planner explicitly does not "interpret execution
results."

### Flow diagram

```text
"When was the last protest in India, what was it about,
 who organized it, what was the outcome?"
        |
        v
  (recognized as needing live info — by Ollama's tool-calling
   decision today, or a future reasoning Module)
        |
        v
  Goal("search", capability_id="web.search", inputs={query, max_results})
        |
        v
  Planner.plan()
        |-- CapabilityResolver.resolve() -> category=TOOL
        |-- ResourceManager.get_resource_snapshot()
        |-- PolicyEngine.evaluate()       -> ALLOW / DENY
        |-- select_tool()                 -> tool.web_search
        v
  ExecutionPlan[ PlanStep(target=TOOL, identifier=tool.web_search) ]
        |
        v
  TaskManager.create()+execute()
        |
        v
  CapabilityExecutor.execute()
        |
        v
  ToolManager.execute(tool.web_search, ToolRequest(query=...))
        |
        v
  WebSearchToolDriver.execute()
        |-- SearchBackend.search()  (default provider, or FailoverSearchBackend
        |     across [web_search].provider_order; retry + timeout per provider)
        |     -> tuple[SearchResult, ...]
        |-- [optional] PageFetcher.fetch() per result (if include_content)
        v
  ToolResponse(result=tuple[dict, ...], attributes={query, result_count})
        |
        v
  (flows back up unopened through every layer)
        |
        v
  BrainResponse.results[0].response  ->  raw search results

  [NOT YET IMPLEMENTED: a second, dependent Goal feeding these
   results into an LLM Provider call to synthesize a cited answer.
   The two-Goal dependency shape to do this is already supported by
   Planner/Brain today; only the automatic result-to-input threading
   between Goals is missing.]
```

**Update (this milestone):** the two-Goal dependency shape described above
is still not automatically wired — that remains accurate. However, an
equivalent outcome is now achieved through a *different*, already-shipped
mechanism: the Ollama provider's own native tool-calling loop
(`OllamaProviderDriver.chat()`). A single `chat.respond` Goal, submitted by
the PARIKA Console (`parika/console/`, formerly the "CLI Interface"),
results in the *model itself* deciding to call `web_search`, PARIKA
resolving that call through a nested `Brain.handle()` call (still through
Planner, still never bypassing it), and the *same* model synthesizing the
final, cited answer once the tool result is fed back into the
conversation — all within one outer Goal/Task cycle from the Console's
point of view. See `Running.md` section 8.3 and
`Request_Execution_Examples.md` section 15 for the concrete walkthrough,
and `tests/integration/test_chat_pipeline.py` for the automated coverage.

------------------------------------------------------------------------

# 13. Summary Table: Who Decides What

| Decision | Decided by | Data in | Data out |
|---|---|---|---|
| Does this capability exist / is it enabled? | `CapabilityResolver` (via `CapabilityRegistry`) | `CapabilityRequest` | `CapabilityResolution` |
| What are current resource conditions? | `ResourceManager` | — | `ResourceSnapshot` |
| Is this Goal allowed to run? | `PolicyEngine` (rules supplied by the Goal's caller) | `PolicyEvaluationRequest` | `PolicyDecision` |
| Tool or Provider? Which one? | `Planner` (`_select_tool`/`_select_provider_model`, delegating PROVIDER scoring to `model_selection.select_provider_model()`) | `CapabilityResolution.definition.category`, `ToolManager`/`ProviderManager` registries, `[model_selection]` configuration | `ExecutionTarget` + backend request |
| Is this operation authorized (ACL-style)? | `PermissionManager` directly (still not invoked by Planner/Brain themselves — available for a Module/Interface to call directly), or, for workspace-scoped access, its `WorkspacePermissionManager` extension, which the Filesystem and Shell Tool drivers consult centrally — see §14 | subject id, operation | `PermissionDecision` / `WorkspacePermissionDecision` |
| When does a Task actually run, and what happens on failure? | `TaskManager` | `TaskRequest` + `CapabilityExecutionRequest` | `Task` (status, response/failure) |
| Which backend actually executes it? | `CapabilityExecutor` | `CapabilityExecutionRequest` | `CapabilityExecutionResponse` |
| What did the Tool/Provider actually do? | `ToolDriver` / `ProviderDriver` | `ToolRequest` / `ProviderRequest` | `ToolResponse` / `ProviderResponse` (opaque to everything above) |
| Did every Goal in this request succeed? | `Brain` | per-Goal `GoalResult`s | `BrainResponse.succeeded` |

------------------------------------------------------------------------

# 14. Workspace Permission Decisions — Filesystem and Shell

**Implementation Status: Live.** This section documents where "may
this path be written/deleted, or may a command run from this
directory" gets decided, now that the System Interaction Foundation
(Shell Tool, Filesystem Tool workspace access model, Workspace
Permission Manager) is implemented and wired into
`build_default_runtime()` — see
[`Core_Component_Responsibilities.md`](Core_Component_Responsibilities.md)
§25 for the Workspace Permission Manager's own design (including what a
"workspace" is, permission scopes, and concurrent-request handling) and
[`../development/Tool_Guide.md`](../development/Tool_Guide.md) §22-23
for how the Shell Tool and Filesystem Tool each consume it. Every
directory shown below is a placeholder for whatever path a real
request actually targets, not a hardcoded PARIKA path.

This decision sits **inside** the Tool layer of §1's pipeline, not
between any of the Core components already documented above — Planner,
`CapabilityResolver`, `ToolManager`, and `CapabilityExecutor` are
unaffected and unchanged by it (§4.4, §7, §8 above still apply exactly
as written once a Tool has been selected). The Filesystem Tool's
`ToolDriver` and a future Shell Tool's `ToolDriver` each ask the same
shared `WorkspacePermissionManager` directly, rather than this decision
being centralized inside `ToolManager` or `Planner`.

## 14.1 Filesystem write outside a trusted workspace

```text
1. Planner selects tool.filesystem_write — unchanged (§4.4)
2. ToolManager.execute() -> FilesystemToolDriver.execute() — unchanged (§8)
3. FilesystemToolDriver asks PathSecurity to resolve the path with operation=WRITE
4. PathSecurity: resolved path is not inside any trusted_workspaces
5. PathSecurity delegates to WorkspacePermissionManager.check(resolved, WRITE)
6. WorkspacePermissionManager.check(resolved, WRITE):
     a. workspace not in trusted_workspaces -> continue to b
     b. no PermissionManager grant already exists for this workspace+operation ->
        continue to c; if one does exist, skip straight to f, authorized
     c. exactly one prompt is shown for this workspace, even if other requests
        for the same workspace arrive concurrently (§14.3)
     d. the user chooses a scope (Once / Session / Permanent / Deny)
     e. Session/Permanent -> PermissionManager.grant(workspace_key, "write", ...)
     f. returns an authorized/denied WorkspacePermissionDecision
7. Authorized -> PathSecurity returns the resolved Path; the write proceeds unchanged
   Denied -> PathNotAllowedError, wrapped into ToolExecutionError like any other
   Filesystem Tool failure
8. Every later filesystem.write/mkdir/copy(dest)/move into the same workspace during
   this run skips the prompt entirely (step 6b now finds the existing grant)
```

## 14.2 Shell execute in an untrusted working directory

```text
1. Planner selects tool.shell_execute — same pipeline shape as any other Tool
2. ToolManager.execute() -> ShellToolDriver.execute()
3. ShellToolDriver resolves cwd, calls
   WorkspacePermissionManager.check(cwd, WorkspaceOperation.EXECUTE)
4. Identical algorithm to §14.1 step 6 (a-f), operation=EXECUTE
5. Authorized -> subprocess.run(command, cwd=cwd, ...) proceeds
   Denied -> ShellToolDriver raises; it never falls back to running the command
   anyway, and never maintains its own allow/deny cache (Tool_Guide.md §22.2)
```

Execute permission is scoped, not analytical — see
`Core_Component_Responsibilities.md` §25 for the rule and
`Tool_Guide.md` §22.2 for why the Shell Tool must not work around it by
parsing commands itself.

## 14.3 Concurrent requests for the same workspace

Step 6b above (and the equivalent step in §14.2) holds regardless of
how many Goals or background Shell processes reach
`WorkspacePermissionManager.check()` for the same workspace at once —
concurrent request coalescing is a property of the Workspace
Permission Manager itself, not something either Tool implements. See
`Core_Component_Responsibilities.md` §25 for the mechanism.
