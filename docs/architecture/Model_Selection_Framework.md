# PARIKA Intelligent Model Selection Framework

**Status:** Live, implemented, and tested. This document describes what
actually exists in the codebase today, not aspirational design.

> **Universal Constraint-Based Model Selection (current design):** the
> framework described in this document now filters candidates through
> an explicit **Task Classification** step (§3a) *before* any scoring
> happens - `User Request -> Requirement Extraction -> Task
> Classification -> Required Model Features -> Candidate Filtering ->
> Capability Validation -> Resource Validation -> Ranking -> Final
> Selection`. This replaced the earlier "score every discovered model
> against every other one" shape with "find models capable of the
> requested task, then rank only those" - the direct fix for failure
> modes like an OCR model being scored for, and winning, an ordinary
> chat request. See §3a, §5, and §6.2 for the concrete mechanics; §11
> for how this stays generic across any current or future provider,
> model, or modality.

------------------------------------------------------------------------

> **Note:** `ExecutionRequirements.tool_calling`/`information_freshness`/
> `capability_hints` are populated exclusively through an explicit
> `Goal.metadata["execution_requirements"]` override supplied by a
> caller (typically AI Context Engineering, in `parika/interfaces/
> chat_capability.py`, before `Brain.handle()` is ever called) -- see
> [`Request_Understanding.md`](Request_Understanding.md). Planner's
> former Requirement Inference framework, which used to derive these
> same fields from a Goal's message text via pattern/regex rules, has
> been removed as part of PARIKA's AI Context Engineering migration.
> Every scoring rule, filter, and the selector in this document's
> scope remains completely unmodified.

> **AI-Assisted Model Selection Refinement (current design):** the
> routing model (the same chat/planner model Planner already selects
> for `chat.respond`, per §1/§2 -- there is no separate "routing model"
> concept or extra LLM call) may now optionally recommend candidate
> worker models and downstream execution requirements for any tool
> call it makes, via one reserved, generic argument
> (`model_selection_hint`). This is layered entirely on top of the
> unchanged filtering/scoring pipeline described below: filtering,
> health, resources, experience, latency, and cost all remain the
> final authority, and the routing model **never** bypasses the
> selector. See §6.3 and §13 for the full mechanics.

> **Configurable Routing Strategy (current design):** Planner can
> optionally skip *scoring* (never filtering) for the routing Goal
> only, and use one operator-pinned model directly instead
> (`[routing_model] mode = "fixed"`), to reduce routing latency for
> small/simple requests. This is the first place the "routing Goal" is
> actually distinguished from any other Goal - by an explicit
> `Goal.metadata` marker the routing Goal's own builder sets, never by
> capability id or any heuristic - but it is still the exact same
> single selection point every other Goal uses; worker model selection
> is entirely unaffected, and the default (`mode = "auto"`) is
> byte-for-byte identical to today's behavior. See §14 for the full
> mechanics.

# 1. Purpose

Before this framework existed, `Planner._select_provider_model()` picked
the first enabled Provider model matching a Capability's required
`ModelCapability`, sorted only by `(provider id, model id)`, with a soft
preference for a `CONNECTED` provider. That produced real problems:

- Slow, reasoning-heavy models got used for simple chit-chat.
- Tool-capable models were not preferred when tool calling would help.
- Nobody could tell *why* a particular model was chosen.

This framework replaces that first-match logic with a deterministic,
weighted, fully configuration-driven scoring pipeline - while changing
**none** of the frozen architecture's component responsibilities.

------------------------------------------------------------------------

# 2. Responsibility Boundaries (read this first)

This is the single most important fact about this framework:

> **Planner still makes every provider/model selection decision. Nothing
> moved to `ProviderManager`.**

- `ProviderManager`'s documented responsibility, unchanged: register,
  store, discover, health-check, and delegate execution to providers. It
  still explicitly **does not** decide which provider or model is used
  (`Core_Component_Responsibilities.md` §14). Its source file
  (`parika/core/provider_manager/provider_manager.py`) was **not
  modified** by this framework.
- Planner's documented responsibility, unchanged: "Execution strategy"
  (`Core_Component_Responsibilities.md` §28). This framework is that
  responsibility, evolved to be smarter, configurable, and transparent -
  not a new responsibility and not somebody else's responsibility.
- The scoring/selection implementation lives entirely inside
  `parika/core/planner/model_selection/`, a subpackage imported **only**
  by `parika/core/planner/planner.py`. It is Planner's own private
  implementation detail, not a new Core component. `ProviderManager` is
  never imported by, and has no awareness of, this subpackage.
- `Brain` and `TaskManager` are untouched.

Everything else in this document describes *how* Planner now makes that
same decision, not a change to *who* makes it.

------------------------------------------------------------------------

# 3. Execution Flow

```text
Brain
  |
  v
Planner.plan()
  |
  v
Planner._select_provider_model()
  |-- build_execution_requirements()      -> ExecutionRequirements
  |     |-- Task Classification: default_task_category_for(category)
  |     |     or an explicit Goal.metadata[...]["task_category"] override
  |     `-- get_task_profile(task_category) -> required_specializations/
  |          required_capabilities/required_modalities/required_execution_features
  |-- model_selection.select_provider_model()
  |     |-- collect every (Provider, ProviderModel) pair
  |     |-- filtering.evaluate_hard_requirements()  -> reject or accept
  |     |     (specialization -> capabilities -> execution features ->
  |     |      modalities -> health -> availability -> context window ->
  |     |      resources; see §6.2)
  |     |-- for each accepted candidate: run every ScoringRule
  |     |-- pick the highest-scoring candidate (deterministic tie-break)
  |     |-- resolve ThinkingMode -> reasoning_enabled (True/False/None)
  |     `-- return ModelSelectionResult
  |-- goal.provider_request_builder(resolution, selected_model)
  |-- apply_reasoning_preference()        -> sets RequestOptions.reasoning
  v
ExecutionTarget(PROVIDER, provider_id, selected_model) + backend_request
```

`ProviderManager.get_all()` is the only thing Planner ever reads from
ProviderManager for this - a plain enumeration, exactly as before.
Ranking (`ScoringRule.evaluate()`) never sees a candidate that failed
filtering - correctness is decided before optimization, not blended
with it.

------------------------------------------------------------------------

# 3a. Task Classification

`parika/core/planner/model_selection/task_classification.py`

Task Classification is the step that turns a resolved Capability's
category into a small, generic statement of *what kind of task* a Goal
represents (`TaskCategory`) and *what a model needs to bring* to even
be considered a candidate for it (`TaskRequirementProfile`). It knows
nothing about providers, models, or provider-specific implementations
- only generic, reusable task vocabulary such as `general_chat`,
`reasoning`, `coding`, `tool_use`, `vision_understanding`, `ocr`,
`image_generation`, `image_editing`, `video_understanding`,
`video_generation`, `speech_to_text`, `text_to_speech`, `translation`,
`embedding`, `reranking`, `planning`, `multimodal`,
`structured_output`. **These are examples, not an exhaustive or closed
list** - see below.

**Classification** (`default_task_category_for()`): a small,
data-only `CapabilityCategory -> TaskCategory` table refines every
category Planner already routes to a Provider (`LLM`, `REASONING`,
`PLANNING`, `VISION`, `OCR`, `EMBEDDING`, `TRANSLATION`, `SPEECH`) with
a richer task classification, without changing which categories are
routable at all - that remains Planner's unmodified responsibility. A
caller may instead supply an explicit `task_category` string via the
same `Goal.metadata["execution_requirements"]` override mechanism
every other requirement dimension already uses - see
`parika/interfaces/chat_capability.py` for where a caller such as AI
Context Engineering could set one.

**Requirement profile** (`get_task_profile()`): every `TaskCategory`
maps to a `TaskRequirementProfile` describing the hard, filtering-stage
requirements a model must satisfy - `required_specializations`,
`required_capabilities`, `required_modalities`,
`required_execution_features` (§6.2 filters on every one of these).
Resolution order: an explicitly `register_task_profile()`-ed profile,
then a built-in example profile (`_BUILTIN_TASK_PROFILES`), then a
generic, synthesized fallback requiring a model to advertise a
specialization equal to the task category's own name - so **a
completely unrecognized task category still filters correctly, with
zero code changes anywhere**.

**Why this is universal, not a growing pile of `if model_name ==
...` branches:**

- Nothing here ever mentions a provider name or a model name - only
  generic strings/enums a Provider chooses to advertise on its own
  `ProviderModel` instances (§5).
- A brand new task category (a future modality PARIKA does not support
  yet) needs no code change at all: a caller supplies its own
  `task_category` string, and `get_task_profile()`'s generic fallback
  makes it filter correctly the moment some Provider advertises a
  matching `specializations` tag.
- A well-known task category that deserves a first-class, documented
  default profile is added as one more `_BUILTIN_TASK_PROFILES` entry
  - a data change, not a change to `filtering.py`, `selector.py`, or
  `planner.py`.
- `register_task_profile()` lets any Module, Interface, or
  application start-up code contribute or override a profile at
  runtime, exactly like `Planner(scoring_rules=...)` already lets an
  embedder extend scoring (§6) without touching this subpackage's own
  source.

------------------------------------------------------------------------

# 4. `ExecutionRequirements`

`parika/core/planner/model_selection/requirements.py`

A frozen, provider-independent statement of *what* a Goal needs. It
**never** contains a provider name, a model name, or a provider-specific
flag - only capability-level needs:

| Field | Meaning |
|---|---|
| `capability` | The `ModelCapability` required (derived from the Capability's category; the one original hard requirement). |
| `reasoning_level` | `SIMPLE` / `NORMAL` / `COMPLEX` - drives both the `ReasoningRule` score and the resolved thinking mode. |
| `task_category` | The `TaskCategory` (or custom string) Task Classification (§3a) resolved for this Goal. Informational/diagnostic; its filtering effect is already fully captured by the four fields below. |
| `required_specializations` | Task Classification's specialization filter (§3a, §6.2). A model reporting *no* `ProviderModel.specializations` at all is never rejected on this dimension - only a model that positively reports specializations excluding every required one is. |
| `required_capabilities` | Additional `ModelCapability` values a model must support, beyond the single `capability` above. Always mandatory when non-empty, exactly like `capability` always was. |
| `required_modalities` | Task Classification's modality filter (§3a, §6.2). Same graceful-degradation semantics as `required_specializations`. |
| `required_execution_features` | Additional `ModelExecutionFeature` values a model must support, beyond `tool_calling`/`structured_output` below. Always mandatory when non-empty. |
| `available_resources` | Optional `ResourceSnapshot` to validate a candidate's `ProviderModel.resource_requirements` against (§6.2). `None` skips resource validation entirely. |
| `latency_preference`, `creativity`, `memory_importance`, `accuracy_preference`, `cost_preference`, `deployment_preference`, `execution_priority` | Captured for forward compatibility (see §9); not yet consumed by a built-in `ScoringRule`. |
| `streaming_required` | Whether the caller wants streamed output. |
| `tool_calling`, `vision`, `structured_output` | `REQUIRED` / `PREFERRED` / `NOT_NEEDED` three-state requirements. |
| `min_context_window` | Optional hard minimum. |
| `metadata` | Free-form extension point for future requirement dimensions that do not yet warrant a dedicated field. |

**How the four `required_*` fields are populated:** `build_execution_
requirements()` calls Task Classification (§3a) to get a
`TaskRequirementProfile` for this Goal's task category, and uses its
`required_specializations`/`required_capabilities`/
`required_modalities`/`required_execution_features` as the defaults for
these four fields - all still overridable, field by field, through the
same `Goal.metadata["execution_requirements"]` mechanism as everything
else in this table.

**How it is built** (`build_execution_requirements()`): Planner starts
from a small, category-driven default (`REASONING`/`PLANNING` ->
`COMPLEX`, everything else -> `NORMAL`), then overlays
`Goal.metadata["execution_requirements"]` if the caller supplied one -
either a fully-built `ExecutionRequirements` instance (used as-is) or a
plain dict of raw values (string enum values are coerced automatically).
**`Goal`'s dataclass shape never changed**: `metadata` is the same
generic mapping it always was.

The shared Interface layer populates this today
(`parika/interfaces/chat_capability.py`, used by both the native
Console and the API layer): `tool_calling=PREFERRED` when
any Tool capability is available to advertise, `NOT_NEEDED` otherwise;
`streaming_required` reflects whether a streaming callback was supplied.

------------------------------------------------------------------------

# 5. Provider-Reported Model Metadata

`ProviderModel` carries three kinds of provider-reported, provider-
independent signal that Task Classification's filtering (§3a, §6.2)
and scoring (§6) read generically. **Nothing here is hardcoded per
model name.**

## 5.1 `specializations` / `supported_modalities`

`frozenset[str]` fields (deliberately plain strings, not a closed
enum) describing which generic *task(s)* a model was tuned or intended
for, and which input/output modalities it supports - e.g.
`specializations={"general_chat"}`, `supported_modalities={"text",
"image"}`. This is the direct data source for `_filter_specialization`/
`_filter_modalities` (§6.2): a model that positively reports a set of
specializations/modalities is only ever a candidate for a task whose
`required_specializations`/`required_modalities` intersect it. An
*empty* set means "the Provider did not report this" - never "this
model has no specialization" - so it is never used to reject a
candidate on its own; this lets the exact same filtering pipeline work
correctly whether or not a given Provider has started advertising this
metadata yet.

Populated today by Ollama (`parika/providers/ollama/model_mapping.py`'s
`specializations_from_show()`/`modalities_from_show()`), derived
conservatively from Ollama's own `/api/show` `capabilities` list
(`"completion"` -> `"general_chat"`, `"embedding"` -> `"embedding"`,
`"thinking"` -> `"reasoning"`; `"vision"` -> modality `"image"`, every
model implicitly supports modality `"text"`) - never a per-model-name
guess (e.g. Ollama never claims `"coding"`, since it does not report
that).

## 5.2 `resource_requirements`

A `ModelResourceRequirements` (`min_ram_bytes`, `min_vram_bytes`,
`min_disk_bytes`, `requires_gpu`, `min_gpu_count`), every field
defaulting to "unreported". This is the data source for
`_filter_resources` (§6.2): a candidate is only ever rejected on
resource grounds when both a specific requirement is declared *and* a
`ResourceSnapshot` was supplied to validate it against
(`ExecutionRequirements.available_resources` - Planner threads through
the same snapshot it already fetches once per `plan()` call via
`ResourceManager.get_resource_snapshot()`). Not populated by Ollama
today (it does not expose hardware requirements per model).

## 5.3 `metadata`

`ProviderModel.metadata` (`Mapping[str, object]`, unchanged) is where
Providers optionally expose extra, well-known signals that scoring
rules read generically. A rule always degrades to a neutral score when
a key is absent, so a Provider that reports nothing still works
correctly; it just does not benefit from that one scoring dimension.

| Key | Type | Meaning | Populated today by |
|---|---|---|---|
| `estimated_latency_ms` | `float` | Coarse expected response latency. | Ollama, from `parameter_size` (see §8). |
| `estimated_throughput_tps` | `float` | Coarse expected tokens/second. | Ollama. |
| `deployment_type` | `str` (`"local"` / `"cloud"`) | Where the model runs. | Ollama (`"local"`, always). |
| `cost_per_1k_tokens` | `float` | Cost signal for `CostRule`. | Not populated by Ollama (free/local); a future cloud provider would set this. |

Any future provider - or a future scoring rule - can introduce a new
metadata key, `specializations` tag, `supported_modalities` tag, or
`resource_requirements` value without touching Planner,
`ProviderManager`, or any other provider's code.

------------------------------------------------------------------------

# 6. Scoring: `ScoringRule`, not a growing pile of functions

`parika/core/planner/model_selection/rules.py`,
`preference_rules.py`

**Design choice made explicitly for long-term extensibility:** rather
than a single module accumulating an ever-growing list of independent
`score_latency()`, `score_reasoning()`, ... functions that
`selector.py` would need to know about individually, every scoring
dimension is a small, independently testable class implementing:

```python
class ScoringRule(ABC):
    id: str

    @abstractmethod
    def evaluate(self, *, provider, model, requirements, config, candidate_pool) -> RuleOutcome: ...
```

`selector.py` only ever iterates over a *sequence* of `ScoringRule`
instances - it never inspects which concrete rules exist. Adding a new
scoring dimension means writing one new class and adding it to the rule
sequence; the selector's orchestration code never changes.

**Built-in weighted rules** (`rules.py`, `DEFAULT_WEIGHTED_RULES`):

| Rule | `id` (matches a weight key) | What it rewards |
|---|---|---|
| `LatencyRule` | `latency` | Lower `estimated_latency_ms`, relative to peers. |
| `ReasoningRule` | `reasoning` | Reasoning-capable models for COMPLEX; mildly *penalizes* them for SIMPLE/NORMAL - the direct fix for "reasoning models used unnecessarily". |
| `ToolCallingRule` | `tool_calling` | Tool-calling support when `PREFERRED`; neutral when `NOT_NEEDED`. |
| `ContextWindowRule` | `context_window` | Larger `ModelLimits.context_window`, relative to peers. |
| `CostRule` | `cost` | Lower `cost_per_1k_tokens`; free/local models score as free. |
| `ExperienceRule` | `experience` | Historical success rate for this capability/provider/model, from an injected `ExperienceSource`. Neutral (opt-in, weight `0.0` by default) when no source or no data is reported. |
| `RoutingRecommendationRule` | `routing_recommendation` | A per-request candidate recommendation from the routing model, read from `requirements.metadata["candidate_models"]` -- see §6.3. Neutral when no recommendation was supplied, or none matches this candidate. |

**Built-in preference (bonus) rules** (`preference_rules.py`,
`DEFAULT_PREFERENCE_RULES`): `LocalDeploymentPreferenceRule`,
`StreamingPreferenceRule`, `HealthierProviderPreferenceRule` - each adds
a small flat bonus (`ModelSelectionConfig.preference_bonus_magnitude`,
default `5.0`) when its `[model_selection.preferences]` flag is enabled
and satisfied.

`DEFAULT_SCORING_RULES` (`model_selection/__init__.py`) is the weighted
rules followed by the preference rules. `Planner(scoring_rules=...)`
accepts a different sequence for embedders who want to add or replace
rules without modifying Planner.

## 6.1 `RuleOutcome` and `CandidateEvaluation`

Every rule returns a `RuleOutcome(rule_id, contribution, raw_score,
weight, note)`, not just a bare number - `raw_score`/`weight` are kept
alongside the final `contribution` specifically for diagnostics, and
`note` is a short, human-readable explanation.

Every *candidate*, whether it survives filtering or not, gets a
`CandidateEvaluation(provider_id, model_id, accepted, total_score,
breakdown, rejection_reason, reason)`. Rejected candidates are recorded
with a `rejection_reason` (e.g. `"provider is disabled"`, `"model does
not support required tool calling"`) rather than being silently
dropped, so "why wasn't model X picked?" is always answerable from the
transparency trail described in §10 - not just for the winner.

## 6.2 Hard requirement filtering pipeline

`filtering.py`'s `evaluate_hard_requirements()` runs before scoring and
composes an **ordered** pipeline of independent filter functions,
stopping at (and returning) the first one that rejects a candidate -
never scored, and recorded with a specific `rejection_reason` (§6.1):

1. **`_filter_specialization`** - the model's *declared*
   `specializations` (§5.1) do not intersect
   `requirements.required_specializations`. Skipped when either side
   is empty (nothing required, or nothing declared) - see §5.1's
   graceful-degradation contract. This is the direct fix for "an OCR
   model gets scored for ordinary conversation": once a Provider
   advertises `specializations={"ocr"}`, that model can no longer even
   be scored for a `general_chat` task.
2. **`_filter_capabilities`** - the model lacks `requirements
   .capability` (the original, single hard requirement), any capability
   in `requirements.required_capabilities`, or (when `vision` is
   `REQUIRED`) `ModelCapability.VISION`.
3. **`_filter_execution_features`** - a `REQUIRED` (not `PREFERRED`)
   `tool_calling`/`structured_output` requirement is unmet, or the
   model lacks any execution feature in `requirements
   .required_execution_features`.
4. **`_filter_modalities`** - the model's *declared*
   `supported_modalities` (§5.1) do not intersect `requirements
   .required_modalities`. Same graceful-degradation contract as step 1.
5. **`_filter_health`** - the Provider's `health.available` is
   explicitly `False` (unknown health, `health is None`, is *not* a
   rejection).
6. **`_filter_availability`** - the Provider is administratively
   disabled (`provider.enabled is False`).
7. **`_filter_context_window`** - `requirements.min_context_window` is
   set and unmet (model's context window is smaller, or unreported).
8. **`_filter_resources`** - the model's declared `resource_
   requirements` (§5.2) are known to exceed `requirements
   .available_resources`. Skipped entirely when no snapshot was
   supplied, or when a specific requirement dimension was never
   declared by the model.

Steps 1, 4, and 8 use the *optional, best-effort* graceful-degradation
contract (unreported is never a rejection); steps 2, 3, 5, 6, and 7 use
the *mandatory* contract every hard requirement already used before
this pipeline existed (a model that does not report a mandatory
capability/feature is always treated as not supporting it). See §5 for
why these two contracts are deliberately different.

## 6.3 Routing Recommendations (`RoutingRecommendationRule`)

`rules.py`

This is the concrete answer to a limitation deterministic filtering
and scoring cannot solve alone: when two or more models advertise the
*same* specialization (e.g. two Vision-capable models both tagged
`vision_understanding`), nothing in §5/§6.2 can tell them apart based
on the actual content of *this specific request*. The routing model
(the same model already selected for `chat.respond`, per §1/§2 -- no
separate model, no extra LLM call) has already read that content, so
it may optionally recommend which candidate(s) fit it best.

**Where the recommendation comes from:** a routing model that decides
to call a tool whose execution will be handled by a specialized,
Provider-backed model may include one reserved, generic argument,
`model_selection_hint`, alongside that tool call's own normal
arguments (see `parika/interfaces/ai_context/model_selection_policy
.py` for the exact instruction text the routing model receives, and
`parika/interfaces/ai_context/worker_inventory.py` for the compact
inventory of other installed models it can choose from -- see §13 for
both). `parika/providers/ollama/tool_calling.py`'s `ToolCallResolver`
pops this one reserved key out of the tool call's arguments (so the
Tool actually being called never sees it as one of its own arguments)
and forwards it as this Goal's `Goal.metadata["execution_requirements"]`
override -- the exact same, pre-existing extension point every other
requirement override already uses (§4). A two-step Tool driver that
itself submits a nested, Provider-backed Goal (`VisionToolDriver`,
`OcrToolDriver`, `StandardCodingAgent`) forwards it one level further,
onto that inner Goal's own `metadata`, via `ToolRequest.metadata`
(already part of `ToolManager`'s public shape, previously always
empty).

**Where it is *not* placed, and why:** `candidate_models` is
deliberately **not** a first-class `ExecutionRequirements` field. A
recommendation is not a requirement -- every other field in §4
describes a property the *selected model itself* must have; a ranked
recommendation is an external, per-turn signal about *which*
candidate to prefer among those that already satisfy every
requirement. It is carried instead under `ExecutionRequirements
.metadata["candidate_models"]`, the framework's own pre-existing
extension point for exactly this kind of future, rule-scoped signal
(§4's `metadata` row).

**How it enters the selector:** `RoutingRecommendationRule` (§6, table
above) reads `requirements.metadata["candidate_models"]` -- a list of
`{"provider_id", "model_id", "confidence"}` objects -- defensively
(any missing/malformed entry is skipped, never an error) and rewards a
matching candidate with that confidence as its raw score, `0.5`
(neutral) for every other candidate. It is one more `ScoringRule`
contribution, nothing more:

- It can never select a candidate that `filtering.py` (§6.2) already
  rejected -- a recommendation for an incompatible or unhealthy model
  simply never matches any surviving candidate.
- It never bypasses `ExperienceRule`, `LatencyRule`, `CostRule`, or any
  other rule -- every rule's contribution is still summed exactly as
  before.
- With no recommendation supplied at all (every request before this
  feature existed, and every request from a routing model that chose
  not to recommend anything), it contributes the same neutral `0.5 *
  weight` to every candidate -- selection is byte-for-byte identical to
  before this rule existed.

**Configuration:** `[model_selection.weights] routing_recommendation`
(default `20.0`, see §9) -- fully tunable, including down to `0.0` to
disable its influence entirely without removing the rule.

> **Selection vs. sizing:** `ContextWindowRule`/`min_context_window`
> above only ever influence *which* model is picked. Once a model *is*
> picked, sizing that model's actual context window for this request
> is a separate, later step: Planner computes a Runtime Context Budget
> from the winning model's own `ModelLimits.context_window`, narrowed
> by `[context_engine]` configuration, and applies it onto
> `RequestOptions.context_window_tokens` (see `PARIKA_Decision_Flow.md`
> section 4.4 and `provider_manager/context_budget.py`) so the Provider
> can size its own context parameter (e.g. Ollama's `num_ctx`)
> dynamically instead of falling back to its own hardcoded default.

------------------------------------------------------------------------

# 7. `ModelSelectionResult`

`selection_result.py`

The selector returns one complete, immutable decision record - not just
the winning `ProviderModel` - specifically so logging, diagnostics, and
any future telemetry/metrics/dashboard consumer can be built against it
without ever needing to change its shape or re-run selection:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelSelectionResult:
    requirements: ExecutionRequirements
    selected_provider_id: str | None
    selected_model: ProviderModel | None
    thinking_mode: ThinkingMode
    reasoning_enabled: bool | None
    total_score: float | None
    breakdown: tuple[RuleOutcome, ...]
    reason: str
    evaluated_candidates: tuple[CandidateEvaluation, ...]
    selection_duration_seconds: float
    evaluated_at: datetime
```

This is intentionally not threaded through `TaskResponse`/`GoalResult`/
`BrainResponse` in this milestone - doing so would touch `TaskManager`
and `Brain`, which this framework deliberately leaves untouched. The
object's shape already supports that extension without redesign,
whenever it is actually needed (see §9).

------------------------------------------------------------------------

# 8. Thinking Mode ("Reasoning" toggle)

Three independent, cleanly separated concerns:

1. **Planner decides *whether* thinking should be requested** -
   generically, from `ExecutionRequirements.reasoning_level` and
   `[model_selection.reasoning]` (`simple`/`normal`/`complex` ->
   `off`/`auto`/`on`). `off`/`on` resolve to an explicit
   `True`/`False`; `auto` resolves to `None` (no explicit override -
   the provider's own default behavior applies).
2. **Planner expresses that preference generically** by setting
   `RequestOptions.reasoning: bool | None` (a new, optional field added
   to the existing, frozen `RequestOptions` dataclass) on whatever
   `ProviderRequest` the Goal's `provider_request_builder` returned
   (`apply_reasoning_preference()` in `selector.py`). This is a no-op
   for `AUTO`, and a no-op if the builder did not return a real
   `ProviderRequest` (defensive - never breaks a builder that returns
   something else, e.g. in tests).
3. **The Provider translates it into its own concrete mechanism.**
   `RequestOptions` and Planner never mention "Ollama" or `think`
   anywhere. `parika/providers/ollama/wire.py` is the *only* place that
   reads `options.reasoning` and sets Ollama's native `think` request
   field, for both `/api/chat` and `/api/generate`. A provider with no
   such concept simply never looks at the field.

**Why `ReasoningRule` also matters here, independently of the toggle:**
real testing against a live Ollama instance showed that even with no
explicit override (`AUTO`), several reasoning-tuned models still think
extensively by default (one observed response took 98 seconds for
"what is 2+2?"). `ReasoningRule` mildly discourages reasoning-heavy
models for `NORMAL`/`SIMPLE` requests specifically so a faster,
equally-capable non-reasoning model is preferred *before* the thinking
toggle even becomes relevant - the toggle alone is not sufficient,
because a model's own template defaults can override "no preference".
Operators who want thinking forced off even for `NORMAL` requests can
simply set `[model_selection.reasoning] normal = "off"`.

**Downstream thinking, decided by the routing model:** since
`reasoning_level` is already an override-able `ExecutionRequirements`
field (§4), the routing model's `model_selection_hint` (§6.3, §13) may
also include a plain `"reasoning_level": "simple" | "normal" |
"complex"` key -- e.g. recommending `"simple"` for a straightforward
OCR/code-generation call, or `"complex"` for a difficult multi-step
analysis. This reuses this exact, unmodified pipeline end to end; no
new reasoning/thinking mechanism was introduced. `ExecutionRequirements
.metadata["candidate_models"]` (§6.3) and `reasoning_level` may be
supplied together in the same hint, since one is a recommendation and
the other a genuine requirement override (§6.3 explains the
distinction).

------------------------------------------------------------------------

# 9. Configuration

`config/defaults.toml`'s `[model_selection]` section, read exclusively
through the existing `Configuration` Core component -
`load_model_selection_config()` (`config.py`) performs nothing but
`Configuration.get()` calls, merged over built-in defaults. **This is
not a parallel configuration system**: there is no second config file,
no second loader, and no state independent of `Configuration`.
`ModelSelectionConfig` is a typed, read-only snapshot taken once when
Planner is constructed.

```toml
[model_selection]
default_strategy = "weighted"
fallback_strategy = "highest_score"
allow_provider_fallback = true
allow_model_fallback = true
enable_dynamic_latency_learning = true
enable_dynamic_performance_learning = true
log_decision = true

[model_selection.weights]
latency = 40
reasoning = 25
tool_calling = 20
context_window = 10
cost = 5
routing_recommendation = 20

[model_selection.preferences]
prefer_local = true
prefer_streaming = true
prefer_healthier_provider = true
prefer_lower_latency = true
prefer_larger_context = false

[model_selection.reasoning]
simple = "off"
normal = "auto"
complex = "on"
```

- **No code change is ever required to tune scoring.** A weight for a
  rule id not present in `[model_selection.weights]` falls back to that
  rule's built-in default, then to `0.0` - it never errors.
- `allow_provider_fallback` / `allow_model_fallback` are read and
  recorded but not yet enforced by additional logic beyond "the best
  available candidate is always used, or none is" - there is currently
  only ever one round of selection per Goal.
- `enable_dynamic_latency_learning` / `enable_dynamic_performance_learning`
  are recognized configuration flags **without a wired implementation
  yet** - they are an explicit extension point (§10), not a feature that
  silently does nothing while claiming to work. Do not rely on them
  changing behavior today.
- `[routing_model]` is a separate, independent section controlling
  only how the *routing* Goal's model is selected (bypassing this
  scoring pipeline entirely when `mode = "fixed"`) - it never changes
  `[model_selection]` itself or worker model selection. See §14.

------------------------------------------------------------------------

# 10. Execution Transparency (Logging)

Every stage logs at DEBUG level (`logging.level = "DEBUG"` in
`config/*.toml`; see `Running.md` §7 for quieting it in interactive use):

- **Planner** (`parika.core.planner.planner` logger, via
  `model_selection/selector.py`): the built `ExecutionRequirements`;
  every evaluated candidate with its full per-rule breakdown, or its
  rejection reason; the final selection (provider, model, score,
  thinking mode, reasoning preference, selection time).
- **Ollama provider** (`parika.providers.ollama.driver`/`.tool_calling`/
  `.chat_loop`, via `transparency.py`): "Sending request", "Streaming
  started", "Tool requested", "Executing tool", "Tool finished",
  "Submitting tool result", "Streaming final response", "Execution
  completed" with total time.

Example (real Ollama, abbreviated):

```text
DEBUG parika.core.planner.planner Model selection requirements: capability=text_generation reasoning_level=normal tool_calling=preferred ...
DEBUG parika.core.planner.planner Candidate provider=provider.ollama model=deepseek-r1:14b score=81.19 breakdown=[latency=27.12, reasoning=20.00, ...]
DEBUG parika.core.planner.planner Candidate provider=provider.ollama model=qwen3-coder:latest score=105.00 breakdown=[latency=40.00, reasoning=25.00, ...]
DEBUG parika.core.planner.planner Selected provider=provider.ollama model=qwen3-coder:latest score=105.00 thinking_mode=auto reasoning_enabled=None selection_time_ms=0.30
DEBUG parika.providers.ollama.driver Sending request: model=qwen3-coder:latest endpoint=/api/chat streaming=False tools=1
DEBUG parika.providers.ollama.driver Execution completed: model=qwen3-coder:latest tool_calls=0 total_time_ms=20883.09
```

`log_decision = false` silences the Planner-side selection logs (the
Ollama-side execution logs are independent of it).

------------------------------------------------------------------------

# 11. Extensibility / Future Work

**Already built, not just designed for** (see §3a and §5):

- **A new provider** - implement its `ProviderDriver`, discover its
  models, and advertise `capabilities`/`execution_features`/
  `specializations`/`supported_modalities`/`resource_requirements`/
  `metadata` on each `ProviderModel`. Nothing else - `filtering.py`,
  `selector.py`, and `planner.py` never change.
- **A new model from an existing provider** - purely a discovery-time
  data change; no code anywhere reads or branches on a model id/name.
- **A new task category** - see §3a's `register_task_profile()`/
  `get_task_profile()` fallback: a caller-supplied `task_category`
  string works correctly even with zero code changes, and a
  first-class one is a one-entry `_BUILTIN_TASK_PROFILES` data addition.
- **A new modality** (audio, video, or something not yet imagined) -
  just another string in `supported_modalities`/`required_modalities`;
  neither is a closed enum.

Designed for, not yet built (per the milestone's own scope):

- **A new scoring dimension** - write a `ScoringRule` subclass, add it
  to the sequence passed to `Planner(scoring_rules=...)` (or add it to
  `DEFAULT_SCORING_RULES` if it should ship by default). No selector or
  Planner change required.
- **A new provider-reported metadata key** - any provider may populate
  any additional `ProviderModel.metadata` key at any time; existing
  rules simply never look at unknown keys, and a new rule can start
  reading a new key without coordinating with any provider.
- **Real observed-latency/performance learning** (the
  `enable_dynamic_*_learning` flags) - the natural hook is
  `Provider`/`ProviderModel` being immutable snapshots refreshed via
  `ProviderManager.discover_models()`/`refresh_health()`; a future
  learning component could accumulate real per-model timing (already
  available on `OllamaChatResponse`/`OllamaGenerateResponse` as
  `total_duration_ns`/`eval_count`) and feed it back into
  `ProviderModel.metadata["estimated_latency_ms"]` on the next
  discovery cycle, entirely inside the Ollama provider package -
  `LatencyRule` would need zero changes to benefit from it.
- **Telemetry/dashboards/historical analysis** - consume
  `ModelSelectionResult` (already a complete, structured record); no
  redesign needed, only a new consumer (e.g. an `EventBus` subscriber
  publishing it, or a `MetricsManager` recording of `total_score` over
  time). Not wired in this milestone to avoid touching `Brain`/
  `TaskManager`.

------------------------------------------------------------------------

# 12. Backward Compatibility

- `Planner.__init__` gained two **optional** keyword parameters
  (`configuration`, `scoring_rules`); every existing call site and test
  that does not pass them is unaffected.
- `RequestOptions` gained one **optional** field (`reasoning: bool |
  None = None`); every existing `RequestOptions()` construction is
  unaffected.
- `Goal`'s dataclass shape is unchanged.
- `ProviderManager` was not modified.
- `ProviderModel` gained three **optional** fields
  (`specializations`, `supported_modalities`, `resource_requirements`),
  every one defaulting to empty/unreported; every existing
  `ProviderModel(...)` construction is unaffected, and the filtering
  pipeline's graceful-degradation contract (§5.1, §6.2) guarantees a
  model that does not populate them is never rejected because of that.
- `ExecutionRequirements` gained five **optional** fields
  (`task_category`, `required_specializations`,
  `required_capabilities`, `required_modalities`,
  `required_execution_features`, `available_resources`), every one
  defaulting to empty/`None`; every existing `ExecutionRequirements
  (...)` construction is unaffected.
- Planner's `CATEGORY_TO_MODEL_CAPABILITY` table (`planner.py`) is
  unchanged - Task Classification (§3a) only ever *refines* an
  already-routable category, it never changes which categories are
  routable to a Provider.
- A `provider_request_builder` that returns something other than a real
  `ProviderRequest` (as `tests/core/planner/test_planner.py` already
  exercises) is left untouched by `apply_reasoning_preference()`.
- `RoutingRecommendationRule` was added to `DEFAULT_WEIGHTED_RULES`;
  `ExecutionRequirements`'s dataclass shape was **not** changed to
  support it (§6.3) -- every existing `ExecutionRequirements(...)`
  construction, and every request with no `metadata["candidate_models"]`
  entry, scores identically to before this rule existed (neutral `0.5`
  contribution for every candidate).
- `Goal.provider_request_builder`'s own signature is unchanged; AI
  Context Engineering's `build_chat_goal()` gained one new **optional**
  `provider_manager` parameter (§13) that every existing call site
  omits, producing byte-identical `OllamaChatRequest` output to before.
- `ToolRequest.metadata` (already part of `ToolManager`'s public
  shape) is now populated by `ToolCallResolver` when a tool call
  carries a `model_selection_hint`; it was always empty before, and
  remains empty for any tool call that does not carry one.

### Addendum: `IMAGE_GENERATION`/`VIDEO_GENERATION` (ComfyUI provider milestone)

The statement above that `CATEGORY_TO_MODEL_CAPABILITY` "is unchanged"
described the framework's state as of that milestone. A later
milestone (adding ComfyUI as a generation Provider — see
`PARIKA_Decision_Flow.md` §8.1) made the framework's first genuinely
*additive* change to that table, needed because no existing
`CapabilityCategory` correctly represented "this Goal needs a model
that generates image/video media" (`VISION` maps to
`ModelCapability.VISION`, the wrong capability for a generation
model):

- Two new `CapabilityCategory` members: `IMAGE_GENERATION`,
  `VIDEO_GENERATION`.
- Two new `CATEGORY_TO_MODEL_CAPABILITY` entries, mapping each to the
  identically-named, pre-existing `ModelCapability.IMAGE_GENERATION`/
  `VIDEO_GENERATION` (these `ModelCapability` members, and their
  corresponding `TaskCategory.IMAGE_GENERATION`/`IMAGE_EDITING`/
  `VIDEO_GENERATION` built-in `TaskRequirementProfile`s in
  `task_classification.py`, already existed before this milestone —
  see that module's own docstring, which explicitly anticipated this).
- Two new `_CATEGORY_TASK_DEFAULTS` entries (`task_classification.py`),
  mapping each new category to its identically-named `TaskCategory`.

Every existing category, mapping, and profile is untouched; no
existing `CapabilityCategory`/`ModelCapability`/`TaskCategory` value
changed meaning. `image.edit`, `video.generate_from_image`, and
`video.edit` each share their sibling operation's `CapabilityCategory`
(so all still require the same single `ModelCapability`) but need a
*different* Provider model (e.g. only a VACE-capable Wan checkpoint
can do image-to-video, not a text-to-video-only one); this
distinction did not require a third new category — it is expressed
entirely through the pre-existing `Goal.metadata
["execution_requirements"]["task_category"]` override (two of these
task categories, `"video_generation_from_image"`/`"video_editing"`,
are not among `task_classification.py`'s built-in examples; they rely
entirely on `get_task_profile()`'s pre-existing generic-fallback
behavior — a `ProviderModel` declaring that exact specialization
string is required, with zero code change to `task_classification.py`
itself).

See `tests/core/planner/test_planner.py` (unmodified, still passing),
`tests/core/planner/model_selection/test_routing_recommendation_rule.py`,
and `tests/core/planner/test_routing_recommendation_integration.py` (a
full, real-`Planner` end-to-end proof that a recommendation flips an
otherwise-tied selection, and that a hard-filtered candidate can never
be selected regardless of any recommendation) for the concrete
verification of all of the above.

------------------------------------------------------------------------

# 13. AI-Assisted Model Selection Refinement (Routing Model, Worker Inventory, PARIKA Model Knowledge)

This section describes the end-to-end feature §6.3 is the scoring-side
half of: how a routing model learns which other models exist, how it
recommends among them, and how PARIKA's own observed knowledge about a
model differs from provider-reported metadata. No Planner, Brain,
Provider abstraction, Capability Registry/Resolver, Tool system,
filtering, scoring, or Capability Executor concept was added, removed,
or redesigned to support any of this -- every piece below is either a
new, narrow rendering/extraction function, or a small, mechanical
forwarding change in a handful of existing files.

## 13.1 Terminology: there is no separate "routing model"

The "routing model" is exactly the `ProviderModel` Planner already
selects for the `chat.respond` Goal (§1/§2) -- the same chat/tool-
calling model PARIKA has always used. There is no additional LLM call
and no new selection step for it. A "worker model" is exactly the
`ProviderModel` Planner selects for a *different*, nested,
Provider-backed Goal a Tool driver submits (e.g.
`vision.provider_describe_image`, `ocr.provider_extract_text`) --
also nothing new; `VisionToolDriver`/
`OcrToolDriver`/`StandardCodingAgent` already worked this way before
this feature existed.

> **Update (§14):** the routing Goal is now explicitly marked, via
> `Goal.metadata[ROUTING_GOAL_METADATA_KEY]` (`parika.core.planner.goal`),
> so `[routing_model] mode = "fixed"` knows which single Goal it may
> apply to. This is a marker on *which Goal is being selected for*, not
> a new selection concept: the marked Goal still goes through
> Planner's one, same `_select_provider_model()` method; only the
> "auto" (score every candidate) vs. "fixed" (use one pinned candidate
> directly) choice for *that specific call* changes. See §14.

## 13.2 Worker Model Inventory

`parika/interfaces/ai_context/worker_inventory.py`

A pure function, `render_worker_inventory(providers, *, exclude=None)`,
renders a compact, semantic, per-turn text block describing every
other installed model, built entirely from `ProviderManager.get_all()`
(zero-I/O, already-cached -- no additional `/api/tags`/`/api/show`
call is ever made). Two kinds of information are rendered per model,
kept strictly separate and never merged:

1. **Objective provider facts** -- `ProviderModel`'s own normalized
   fields: capabilities, specializations, modalities, thinking
   support, tool-calling support, structured-output support,
   streaming support, context window, resource requirements (when
   declared), and the provider-reported description (when available).
   Every segment is omitted, never rendered as a placeholder, when its
   underlying field is unreported/empty -- the same graceful
   degradation contract §5/§6.2 already use.
2. **PARIKA Model Knowledge** -- PARIKA's own observed knowledge about
   a model's real-world strengths (see §13.4), rendered as its own,
   explicitly labeled line ("PARIKA observed knowledge (not
   provider-reported): ..."), never blended into the provider-facts
   segment above.

**Self-exclusion, with no second selection pass:** `exclude` is the
exact `ProviderModel` instance Planner already selected for *this*
Goal. This works because rendering happens *inside* the Goal's own
`provider_request_builder` closure (built by `ai_context.goal_builder
.build_chat_goal()`), which Planner calls at `planner.py:636` --
strictly *after* it has already selected the routing model at
`planner.py:626-628`, and strictly *before* the request is dispatched.
The closure receives that exact, already-selected model as its own
`model` argument and simply omits it while calling the same, already-
cached `ProviderManager.get_all()` every other consumer already reads
from -- no dry-run selection, no duplicated filtering/scoring logic.
`build_chat_goal()`'s new `provider_manager` parameter defaults to
`None`, which skips rendering entirely (§12).

## 13.3 The `model_selection_hint` tool-call argument

`parika/interfaces/ai_context/model_selection_policy.py` (generic
instruction text, composed into the system prompt by `prompt_builder
.build_assistant_system_prompt()`, alongside the existing Reasoning
Policy) tells the routing model it may optionally include one
reserved, generic argument, `model_selection_hint`, on any tool call
whose execution will be delegated to a specialized model. This text
never names a specific Capability, tool, model, or task (the same
Capability Independence contract `reasoning_policy.py` already
follows).

`parika/providers/ollama/tool_calling.py`'s `ToolCallResolver` extracts
this one reserved key before a Tool's own arguments are used
(`_extract_execution_requirements_override()`), and forwards it as
`Goal.metadata["execution_requirements"]` on the outer Tool Goal. Its
shape:

```json
{
  "candidate_models": [
    {"provider_id": "provider.ollama", "model_id": "minicpm-v4.5", "confidence": 0.9}
  ],
  "reasoning_level": "simple"
}
```

`candidate_models` is translated into `metadata.candidate_models`
(§6.3); `reasoning_level`, a genuine `ExecutionRequirements` field, is
forwarded as-is (§8). Every field is optional; a missing or malformed
hint contributes nothing and never raises.

A two-step Tool driver that itself submits a nested, Provider-backed
Goal forwards this override one level further, via `ToolRequest
.metadata["execution_requirements"]` (already part of `ToolManager`'s
public shape), onto that inner Goal's own `metadata`:
`VisionToolDriver._analyze()`, `OcrToolDriver._recognize()`, and
`StandardCodingAgent._submit_decomposition_goal()` (via
`CodingTaskDescriptor.metadata`, forwarded by `CodingAgentToolDriver
.execute()`) each gained exactly this one small, mechanical forwarding
step. A Tool driver that never reads `ToolRequest.metadata` is
completely unaffected.

## 13.4 PARIKA Model Knowledge

`parika/core/semantics/model_knowledge.py` (evolved from the former
`overrides.py` -- see `docs/development/Module_Guide.md`)

Owns two deliberately separate, hand-maintained data tables, both
keyed by exact model base name:

1. **Local Curated Override** (`SpecializationOverride`/
   `get_override()`) -- unchanged in role: PARIKA's curated
   corrections to a model's *provider-facing* `ProviderModel
   .specializations` (§5.1), still consumed only by `resolution
   .resolve_specializations()`, still feeding the exact same filtering/
   scoring pipeline as before.
2. **PARIKA Model Knowledge** (`ModelKnowledgeEntry`/
   `get_model_knowledge()`) -- new: PARIKA's own observed knowledge
   about a model's real-world strengths (e.g. `ocr`,
   `document_understanding`, `ui_analysis`, `chart_analysis`,
   `refactoring`, `code_generation`), obtained through benchmarking,
   manual testing, or evaluation. **Never provider metadata, and never
   fed into `ProviderModel`, `filtering.py`, or `rules.py`** -- it
   exists solely to be surfaced inside the Worker Model Inventory
   (§13.2), for the routing model's own reasoning. Deliberately a
   plain, hand-maintained data table today, kept behind the one
   narrow `get_model_knowledge()` lookup function precisely so a
   future benchmark-driven source can replace or augment it without
   any consumer changing.

## 13.5 Full data flow

```text
ProviderManager.get_all()
  -> worker_inventory.render_worker_inventory(providers, exclude=routing_model)
  -> injected as one more OllamaMessage, inside goal_builder's
     provider_request_builder closure (after routing model selection,
     before dispatch)
  -> routing model's /api/chat request

routing model's tool call (model_selection_hint argument)
  -> tool_calling.ToolCallResolver (extracts the reserved key)
  -> outer Tool Goal.metadata["execution_requirements"]
  -> ToolRequest.metadata (already-existing pass-through)
  -> two-step Tool driver forwards it to its own inner Goal.metadata
  -> build_execution_requirements() (unchanged) -> ExecutionRequirements
       .metadata["candidate_models"] / .reasoning_level
  -> filtering.evaluate_hard_requirements() (unchanged, unaffected)
  -> rules.RoutingRecommendationRule (+ every other unchanged rule)
  -> selector._select_best() (unchanged) -> final worker model
```

------------------------------------------------------------------------

# 14. Configurable Routing Strategy (`[routing_model]`)

## 14.1 Problem this solves

Once a routing model is introduced (§13), the routing model itself is
still selected through the exact same `[model_selection]`
scoring pipeline every other Goal uses. For very small, simple
requests ("Hello", "Thank you", a trivial weather question), the
weighted scoring pipeline can still deterministically prefer a large,
reasoning-heavy model over a much smaller, faster one, adding tens of
seconds of latency to route a one-line request - defeating one of the
routing model's own purposes. This section describes the opt-in fix:
letting an operator pin a specific, known-fast model for routing,
without touching filtering, scoring, worker selection, or any other
part of this framework.

## 14.2 What changed, precisely

**Exactly one new decision point, inside the one method that already
existed:** `Planner._select_provider_model()` (`planner.py`) now
checks, immediately before calling `selector.select_provider_model()`
(the unchanged "auto" pipeline):

```python
selection = None

if self._routing_config.is_fixed and goal.metadata.get(
    ROUTING_GOAL_METADATA_KEY
) is True:
    selection = select_fixed_routing_model(
        providers=self._provider_manager.get_all(),
        requirements=requirements,
        routing_config=self._routing_config,
        logger=self._logger,
    )

if selection is None:
    selection = select_provider_model(...)  # unchanged "auto" pipeline
```

- `self._routing_config` is a `RoutingConfig` snapshot
  (`model_selection/routing_config.py`), loaded once at Planner
  construction time via `load_routing_config(configuration)` -
  the exact same `Configuration.get()`-only pattern
  `load_model_selection_config()` already established for
  `[model_selection]` (§9). No parallel configuration system.
- `ROUTING_GOAL_METADATA_KEY` (`parika.core.planner.goal`) is a plain
  `Goal.metadata` boolean key. It is set **only** by
  `interfaces/ai_context/goal_builder.build_chat_goal()`, the single
  function that builds the `chat.respond` Goal (§13.1) - never by
  capability id, category, or any heuristic. Every worker Goal a Tool
  driver submits never sets it, so `[routing_model]` can never
  affect worker model selection, by construction.
- `select_fixed_routing_model()` (`model_selection/routing_strategy
  .py`) is the only new function. It never duplicates selection
  logic: candidate discovery still reads the same
  `ProviderManager.get_all()` snapshot, and hard-requirement
  compatibility is still checked through the exact same, unmodified
  `filtering.evaluate_hard_requirements()` every "auto" candidate is
  evaluated against. It only ever skips the **scoring** step
  (`rules.py`/`preference_rules.py`/`selector._select_best()`) for
  this one Goal, because the operator has already made that choice
  explicit. Its return type is the exact same `ModelSelectionResult`
  §7 already documents, so every downstream consumer (`planner.py`'s
  `apply_reasoning_preference()`, `apply_context_budget()`, the
  built `ExecutionTarget`) is unaware anything different happened.
- No new Planner, no new Selector, no new Provider abstraction, and no
  bypass of `filtering.py`/`selector.py`/`Capability Executor`.

## 14.3 `[routing_model]` configuration

```toml
[routing_model]
mode = "auto"        # "auto" (default) | "fixed"
fixed_model = ""      # e.g. "qwen3:8b", or "provider.ollama/qwen3:8b"
fixed_thinking = false
```

- **`mode = "auto"`** (the default, and the value used when
  `[routing_model]` is absent entirely, or `Configuration` itself is
  `None`): the routing Goal is selected exactly like before this
  section existed - **zero behavior change**.
- **`mode = "fixed"`**: the routing Goal's selection is resolved
  directly from `fixed_model`, skipping scoring for it. Worker Goal
  selection is unaffected either way (§14.2).
- **`fixed_model`**: either a bare model id (`"qwen3:8b"`, matched
  against any registered Provider) or a `"provider_id/model_id"` pair
  (`"provider.ollama/qwen3:8b"`) to disambiguate when more than one
  Provider could expose the same model id - the same
  `"{provider.id}/{model.id}"` convention `worker_inventory.py` (§13.2)
  already uses. An unrecognized `mode` value is treated as `"auto"`.
- **`fixed_thinking`**: the `RequestOptions.reasoning` value forced for
  the routing model when `mode = "fixed"`, instead of the automatic,
  `ExecutionRequirements.reasoning_level`-derived `thinking_mode` every
  other Goal still uses (§8). Setting it to `false` alongside a small,
  fast `fixed_model` (e.g. `qwen3:8b` with thinking disabled) is the
  main latency win this section exists for. Has no effect when
  `mode = "auto"`.

## 14.4 Validation and fallback (never crashes)

`select_fixed_routing_model()` never raises. Every failure mode logs a
single WARNING (`parika.core.planner.planner`, matching this
framework's existing degraded-path logging conventions, §10) and
returns `None`, which Planner treats identically to "use the unmodified
`select_provider_model()` call for this Goal":

- `fixed_model` is empty (`mode = "fixed"` configured without a model).
- The configured model id (and Provider id, if qualified) is not found
  among any currently registered Provider - not installed, discovery
  has not run yet, or the Provider itself was never registered.
- The configured model is found, but fails
  `filtering.evaluate_hard_requirements()` - e.g. its Provider is
  disabled (`_filter_availability`), its Provider is reporting
  unhealthy (`_filter_health`), or the model itself does not satisfy
  the Goal's required capability/specialization/modality/context
  window/resources. This is the same unmodified filtering pipeline
  §6.2 already documents; a pinned model is never exempt from it.

In every one of these cases, execution continues exactly as it would
under `mode = "auto"` for that single request - including raising
`NoAvailableProviderModelError` if "auto" itself finds no candidate
either, exactly like today.

## 14.5 Backward compatibility

- `[routing_model]` absent from `config/defaults.toml` (or any
  config layer), or `Planner` constructed with `configuration=None`:
  `RoutingConfig()` defaults to `mode = "auto"`, so behavior is
  byte-for-byte identical to before this section existed.
- A Goal built by any caller other than `goal_builder.build_chat_goal()`
  never carries `ROUTING_GOAL_METADATA_KEY`, so it is never eligible
  for the "fixed" short-circuit regardless of `[routing_model]`
  configuration - this includes every existing worker Goal a Tool
  driver submits (§13.1) and every test fixture written before this
  section existed.
- `RoutingRecommendationRule` (§6.3), `ExperienceRule`, every
  preference rule, the Runtime Context Budget computation, and the
  `reasoning`/`context_window_tokens` application onto the built
  `ProviderRequest` are all completely unmodified and apply identically
  regardless of `[routing_model] mode`.
- The legacy `[planner.routing]` namespace is still read by
  `load_routing_config()` as a per-key fallback when `[routing_model]`
  does not define that key, so existing configuration files continue
  to work unchanged. `[routing_model]` always takes precedence when
  both namespaces define the same key.

## 14.6 Testing

- `tests/core/planner/model_selection/test_routing_config.py` - unit
  tests for `load_routing_config()`'s defaults, mode validation, and
  `fixed_model` parsing.
- `tests/core/planner/model_selection/test_routing_strategy.py` - unit
  tests for `select_fixed_routing_model()`: resolution,
  `fixed_thinking` mapping, and every fallback-to-`None`-with-a-warning
  path (not configured, not registered, hard-filtered).
- `tests/core/planner/test_routing_strategy_integration.py` - full
  `Planner.plan()` integration tests: `mode = "auto"` is unchanged;
  `mode = "fixed"` overrides the scoring outcome and applies
  `fixed_thinking` onto the built `ProviderRequest`; a missing/
  unavailable fixed model falls back to the exact "auto" outcome with
  a logged warning; a worker Goal alongside a fixed routing Goal is
  unaffected; a Goal that never sets `ROUTING_GOAL_METADATA_KEY` is
  never treated as the routing Goal even when its capability id
  matches `chat.respond`.
