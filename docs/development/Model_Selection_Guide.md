# Model Selection Development Guide

**Audience:** Contributors adding a new scoring dimension, a new
Provider metadata signal, or tuning selection behavior.

**Status:** Describes the live implementation in
`parika/core/planner/model_selection/`. See
[`Model_Selection_Framework.md`](../architecture/Model_Selection_Framework.md)
for the full architectural description and
[`adr/0001-intelligent-model-selection.md`](../architecture/adr/0001-intelligent-model-selection.md)
for why it is designed this way. This guide is the "how do I..." complement
to those two documents.

------------------------------------------------------------------------

## 1. Design Goals

- Planner decides; nothing else does. Never add code anywhere else
  (Providers, Modules, Interfaces) that picks a model.
- Never hardcode a provider name, a model name, a capability, a score,
  or a weight. Every number lives in `config/*.toml`; every capability
  signal comes from `ProviderModel`.
- Every scoring dimension is independently testable and pluggable.
- A rejected candidate is exactly as visible as the winner.

## 2. Where Things Live

```text
parika/core/planner/model_selection/
├── task_classification.py  TaskCategory, TaskRequirementProfile, get_task_profile()
├── requirements.py     ExecutionRequirements + enums + build_execution_requirements()
├── config.py            ModelSelectionConfig + load_model_selection_config()
├── rules.py              ScoringRule ABC, RuleOutcome, weighted dimension rules
├── preference_rules.py   Boolean-preference bonus rules
├── filtering.py          Ordered hard-requirement filtering pipeline (before scoring)
├── evaluation.py         CandidateEvaluation
├── selection_result.py   ModelSelectionResult
└── selector.py            Orchestrates filter -> score -> pick -> log
```

Everything here is imported only by `parika/core/planner/planner.py`.
Never import this subpackage from `ProviderManager`, a Provider, a
Module, or an Interface.

## 3. Data Flow

```text
Goal (+ optional Goal.metadata["execution_requirements"])
  -> build_execution_requirements()
       -> Task Classification: default_task_category_for(category)
          or an explicit "task_category" override
       -> get_task_profile(task_category)  -> TaskRequirementProfile
       -> ExecutionRequirements (capability + task profile + overrides)
  -> select_provider_model(providers, requirements, config, rules, logger)
       -> evaluate_hard_requirements() per candidate, in order:
            1. specialization filter      (optional metadata, degrades gracefully)
            2. capability filter          (mandatory: capability + required_capabilities + vision)
            3. execution feature filter   (mandatory: tool_calling/structured_output + required_execution_features)
            4. modality filter            (optional metadata, degrades gracefully)
            5. provider health filter
            6. provider availability filter
            7. context window filter
            8. resource filter            (optional metadata, degrades gracefully)
          -> reject (with a specific reason) or continue to scoring
       -> ScoringRule.evaluate() per rule per accepted candidate
       -> pick highest total_score (deterministic tie-break)
       -> resolve ThinkingMode -> reasoning_enabled
  -> ModelSelectionResult
  -> apply_reasoning_preference(backend_request, result.reasoning_enabled)
```

Only candidates that survive every filtering step are ever scored -
ranking never gets a chance to let a faster-but-wrong model win over a
correct one. See §7 and §8 below for the two new dimensions
(specializations/modalities and resource requirements) this adds on
top of the original weighted-scoring design.

## 4. How To: Add a New Scoring Dimension

1. Decide its config key (e.g. `"vision_quality"`). This is what
   operators will write under `[model_selection.weights]`.
2. Write a new `ScoringRule` subclass in `rules.py` (or a new module if
   it does not belong with the built-in five):

   ```python
   class VisionQualityRule(ScoringRule):
       id = "vision_quality"

       def evaluate(self, *, provider, model, requirements, config, candidate_pool):
           # Read only ExecutionRequirements + ProviderModel + config.
           # Return a RuleOutcome; contribution is what gets summed.
           raw_score = ...  # normalize to [0, 1] when reasonably possible
           weight = config.weight_for(self.id)
           return RuleOutcome(
               rule_id=self.id,
               contribution=raw_score * weight,
               raw_score=raw_score,
               weight=weight,
               note="...",
           )
   ```
3. Add an instance to `DEFAULT_WEIGHTED_RULES` (`rules.py`) if it should
   ship on by default, or leave it out and let an embedder pass it via
   `Planner(scoring_rules=(*DEFAULT_SCORING_RULES, VisionQualityRule()))`.
4. Add a default weight to `DEFAULT_WEIGHTS` in `config.py` **only** if
   you want it to contribute something even when nobody configures it.
   A rule with no configured *and* no default weight simply contributes
   `0.0` - it never raises.
5. Document the new weight key in
   `Model_Selection_Framework.md` §6 and in `config/defaults.toml`'s
   comments.
6. Write unit tests mirroring `tests/core/planner/model_selection/test_rules.py`:
   construct two candidates that should score differently on this
   dimension, and assert the direction of the difference - not exact
   numbers, since normalization is relative to the candidate pool.

**Never** make `evaluate()` depend on anything other than its five
parameters. It must stay a pure function of `(provider, model,
requirements, config, candidate_pool)`.

## 5. How To: Add a New Preference (Boolean Bonus)

Same shape as §4, but in `preference_rules.py`, returning `contribution
= config.preference_bonus_magnitude if <condition> else 0.0` instead of
a weighted `raw_score * weight`. Add it to `DEFAULT_PREFERENCE_RULES`
and document the new `[model_selection.preferences]` key.

## 6. How To: Expose New Provider Metadata

Any Provider may add any key to `ProviderModel.metadata` at any time -
this requires zero coordination with Planner or any other Provider.
Pick a name that describes what it *is* generically (e.g.
`"cost_per_1k_tokens"`, not `"ollama_cost"`), document it in
`Model_Selection_Framework.md` §5, and read it with `.get(key)` (never
`[key]`) from whichever `ScoringRule` wants to use it, always handling
"missing" as "neutral," not as an error.

See `parika/providers/ollama/discovery.py` and `latency_estimation.py`
for the reference implementation (`estimated_latency_ms`,
`estimated_throughput_tps`, `deployment_type`), all derived from data
Ollama itself reports - never a hardcoded model name.

## 7. How To: Support a New Capability Category

If a new `CapabilityCategory` needs to route to a Provider, first add it
to `CATEGORY_TO_MODEL_CAPABILITY` in `planner.py` (unrelated to this
subpackage - that mapping predates it). Then, if that category should
default to a non-`NORMAL` `reasoning_level`, add it to
`_CATEGORY_DEFAULT_REASONING_LEVEL` in `requirements.py`. If it should
also get a default Task Classification profile (see §7a), add it to
`_CATEGORY_TASK_DEFAULTS` in `task_classification.py`.

## 7a. How To: Support a New Task Category (No Planner Change Required)

This is the extension point that makes the framework generic across
never-yet-seen task types (a future image-editing provider, a future
video-generation provider, ...) **without touching Planner, the
selector, or the filtering pipeline**:

1. Prefer not editing any code at all first: a caller can already pass
   an arbitrary `task_category` string through `Goal.metadata
   ["execution_requirements"]["task_category"]`. Even a task category
   nobody has ever registered a profile for still gets a sensible
   generic profile (`get_task_profile()` falls back to requiring a
   `ProviderModel.specializations` tag equal to the task category's
   own name) - so a brand new Provider can go live the moment it starts
   advertising a matching `specializations` string, with zero code
   changes anywhere in PARIKA.
2. If the new task category is common enough to deserve a proper,
   documented default profile, call `register_task_profile()` once
   (e.g. from a Module's or Interface's start-up code) with a
   `TaskRequirementProfile` describing its
   `required_specializations`/`required_capabilities`/
   `required_modalities`/`required_execution_features`. This still
   never touches `task_classification.py`, `filtering.py`,
   `selector.py`, or `planner.py`.
3. Only add a new `TaskCategory` enum member and a
   `_BUILTIN_TASK_PROFILES` entry in `task_classification.py` itself
   when the task category is a well-known, first-class PARIKA concept
   that should ship by default (mirroring how `DEFAULT_WEIGHTED_RULES`
   works for scoring dimensions in §4) - this is a data change, not a
   change to any selection logic.
4. If the category should also be reachable through the existing
   `CapabilityCategory` routing (rather than only via an explicit
   `task_category` override), see §7's `_CATEGORY_TASK_DEFAULTS` entry.

## 7b. How To: Expose New Specialization/Modality Metadata

Any Provider may add any string to `ProviderModel.specializations`/
`.supported_modalities` at any time - these are deliberately plain
strings, not a closed enum, for the same reason `ProviderModel
.metadata` is an open mapping (see §6). Two rules keep this safe:

- **Only advertise what is actually true.** Derive the tag from data
  the Provider's own discovery API reports (see
  `parika/providers/ollama/model_mapping.py`'s
  `specializations_from_show()`/`modalities_from_show()` for the
  reference implementation - it maps Ollama's own `capabilities` list
  to generic tags like `"general_chat"`/`"reasoning"`/`"embedding"`,
  and deliberately never claims something Ollama does not report,
  e.g. `"coding"`). Never fabricate a specialization from a model's
  name.
- **Report nothing when unknown**, rather than guessing. An empty
  `specializations`/`supported_modalities` set is never treated as a
  rejection by `filtering.py` - "unreported" and "not this task" are
  different things, and only the latter should ever filter a
  candidate out. The one exception: `required_capabilities`/
  `required_execution_features` are always mandatory, exactly like
  the original `capability`/`execution_features` fields.

## 8. How To: Add a Resource Requirement to a Model

Populate `ProviderModel.resource_requirements` with a
`ModelResourceRequirements` (`min_ram_bytes`, `min_vram_bytes`,
`min_disk_bytes`, `requires_gpu`, `min_gpu_count`) from your Provider's
own discovery data - every field defaults to "unreported", so partially
populating it (e.g. only `requires_gpu=True`) is always safe.
Validation against the current machine only happens when Planner is
given a resource snapshot (`ExecutionRequirements.available_resources`,
already threaded through automatically from `ResourceManager
.get_resource_snapshot()` - see `planner.py`); with no snapshot,
`filtering.py`'s resource step is a no-op, exactly like every other
optional signal in this framework.

## 10. How To: Tune Selection Without Touching Code

Everything in §9 of `Model_Selection_Framework.md` is a TOML edit, in
whichever layer (`config/workspace.toml`, `config/runtime.toml`, ...) is
appropriate. Common tuning tasks:

- **Make selection latency-insensitive:** set
  `[model_selection.weights] latency = 0`.
- **Force thinking off everywhere:** set every entry in
  `[model_selection.reasoning]` to `"off"`.
- **Turn off a boolean preference:** set the matching
  `[model_selection.preferences]` key to `false`.
- **See every decision Planner makes:** ensure
  `logging.level = "DEBUG"` and `model_selection.log_decision = true`
  (both are already the shipped defaults).

## 11. Common Mistakes to Avoid

- **Do not** put selection logic in `ProviderManager`, a Provider, or an
  Interface. If you find yourself wanting to, you are solving the wrong
  layer's problem - express it as an `ExecutionRequirements` field (via
  `Goal.metadata["execution_requirements"]`) and a `ScoringRule`
  instead.
- **Do not** filter by specialization/modality inside a `ScoringRule`.
  Filtering (specialization, capabilities, modalities, health,
  availability, context window, resources) always happens in
  `filtering.py`, strictly before scoring - ranking must never be able
  to let an unsuitable candidate win just because it scores well on
  latency or cost. See §3's ordered pipeline.
- **Do not** hardcode a model or provider name inside a rule, even as a
  "temporary special case." Every existing rule works for any provider
  and any model precisely because it never does this.
- **Do not** assume a metadata key exists. Always use `.get(...)` with a
  sensible neutral fallback.
- **Do not** add a new required (non-optional) parameter to
  `Planner.__init__` or a new required field to `RequestOptions` -
  existing callers and tests must keep working unmodified. Add optional
  parameters/fields with safe defaults instead.
- **Do not** assume `provider.state is ProviderState.CONNECTED` is
  meaningful on its own for correctness - today it is only ever a small
  preference bonus (`HealthierProviderPreferenceRule`), because nothing
  in the current architecture actually transitions that state (see
  `ProviderManager`'s "Does NOT: Manage provider connection state
  transitions"). Use `provider.health.available` for real
  availability checks.

## 12. Where to Look for Examples

- `tests/core/planner/model_selection/` - unit tests for every piece
  described above, including `test_task_classification.py` (Task
  Classification) and `test_task_based_selection_regressions.py`
  (the OCR-vs-chat, coding, vision, image-generation, speech,
  reasoning, and tool-calling regression scenarios, exercised through
  the full `build_execution_requirements()` -> `select_provider_model()`
  pipeline).
- `tests/core/planner/test_planner_model_selection.py` - Planner-level,
  multi-candidate integration tests.
- `tests/providers/ollama/test_model_mapping.py` - the reference
  `specializations_from_show()`/`modalities_from_show()`
  implementation, showing how to derive generic tags from a real
  Provider's own discovery data without fabricating anything.
- `tests/providers/ollama/test_ollama_driver.py::TestReasoningPassthrough`
  and `test_latency_estimation.py` - the Provider side of the
  `reasoning`/`think` translation and metadata population.
- `tests/integration/test_chat_pipeline.py` - the whole thing, real Core
  stack, exercised end to end (with only the outermost transports
  faked).
