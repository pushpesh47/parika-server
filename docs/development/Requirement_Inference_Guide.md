# Adding a New Capability (Post-AI Context Engineering)

**Audience:** Contributors adding a new capability domain (filesystem,
email, calendar, database, code execution, ...) that should be usable
in chat.

**Status:** This guide previously described how to add a new
`InferenceRule` to Planner's pattern/regex-based Requirement Inference
framework. That framework has been **completely removed** as part of
PARIKA's AI Context Engineering migration - see
[`Request_Understanding.md`](../architecture/Request_Understanding.md)
for the full architectural description and the rationale for removing
it. This guide now describes the "how do I..." complement to that
document: what actually needs to happen to make a new capability
usable by the model.

------------------------------------------------------------------------

## 1. What You No Longer Need to Do

There is no `InferenceRule` to write, no domain regex pattern to add
anywhere, and no `CapabilityHint` enum member required for ordinary
tool advertisement. `parika/core/planner/requirement_inference/` no
longer exists. `parika/interfaces/tool_relevance.py` no longer exists.
Nothing in `parika/interfaces/chat_capability.py` or
`parika/interfaces/ai_context/` needs to change to make a new
Capability advertisable to the model, discoverable, or schema-described
-- AI Context Engineering owns zero capability-specific knowledge (see
`Request_Understanding.md`'s Capability Independence rule).

## 2. What You Do Need to Do

Follow [`Capability_Guide.md`](Capability_Guide.md) and
[`Tool_Guide.md`](Tool_Guide.md) exactly as you would for any other
capability:

1. **Capability Registration** - register a `CapabilityDefinition`
   (id, name, description, category) with `CapabilityRegistry`.
2. **Capability Metadata** - write a clear, plain-language
   `description`. This is not just documentation: it is read by the
   model directly as the tool's description in the native
   tool-calling schema (unless overridden by your own Tool Affordance
   Contract, see step 5), so it doubles as the capability's
   "affordance" description (see `Request_Understanding.md` §5).
   Prefer concrete phrasing over a raw identifier - e.g. "Reads the
   text content of a file." rather than leaving the model to infer
   meaning from `filesystem.read` alone.
3. **Tool Registration** - register a `Tool` with `ToolManager` (for a
   TOOL-category Capability), following the existing "one Tool per
   Capability" pattern already used by Filesystem/Shell/Coding/News/
   Weather/Currency (see any of those `manifest.py` files as a
   template).
4. **Permission Rules** - only if the new Capability needs one; no
   change to the Permission System itself.
5. **(Optional, recommended) Your own Tool Affordance Contract.**
   `Tool` does not itself carry an input JSON Schema or reasoning
   guidance, so define both in your own Tool's `manifest.py` (see
   e.g. `WEATHER_TOOL_AFFORDANCES` in `parika/tools/weather/
   manifest.py`) as a plain mapping with any subset of `name`,
   `description`, `purpose`, `use_when`, `avoid_when`, `requires`,
   `result_semantics`, `failure_semantics`, and `parameters` keys
   (see `Request_Understanding.md` §4.4 for what each renders as),
   then pass it as `metadata={"tool_affordance": ...}` when
   constructing the `CapabilityDefinition` in your Module driver's
   `start()` (see `parika/modules/weather/driver.py`). This is
   entirely optional and additive: any Capability without one still
   gets advertised automatically with its plain `description` and a
   permissive generic schema, so a model can still call it - the
   richer fields only improve *when*/*why*/*how* the model reasons
   about calling it. AI Context Engineering (`ai_context/
   tool_context.py`) only ever *reads* this metadata generically -- it
   never defines, hardcodes, or special-cases any capability's
   contract (Capability Independence).

Once steps 1-3 are done and the Capability is enabled,
`ai_context.capability_context.discover_capabilities()` and
`ai_context.tool_context.discover_tool_specs()` advertise it
automatically, every turn, with zero further code changes anywhere in
`parika/interfaces/`.

## 3. If a Capability Needs Authorization Beyond Permission Rules

Ordinary tool advertisement never requires this. If your new
Capability genuinely needs a turn-by-turn authorization check before
it is even advertised (the Memory Capabilities are the only precedent
today -- see `parika/tools/memory/manifest.py`'s
`MEMORY_IDENTITY_SENSITIVE_CAPABILITIES` and
`parika/tools/memory/intent.py`'s `has_explicit_memory_intent`), set
one or both of these metadata keys on your own `CapabilityDefinition`,
alongside `tool_affordance`:

- `identity_sensitive: bool` - excludes this Capability from the
  roster whenever the current turn is recognized as an Assistant
  Identity question.
- `authorization_predicate: Callable[[str], bool]` - an opaque check
  your own Tool/Module owns and passes in; AI Context Engineering
  calls it with the current message text and excludes the Capability
  when it returns `False`, without ever knowing what it checks.

Both are read generically by `ai_context.tool_context.
discover_tool_specs()` -- adding either requires no change there.
This is a fixed-scope authorization mechanism, not a place to build a
capability router: do not use `authorization_predicate` to decide
*whether a capability is relevant*, only whether it is *permitted* for
this turn at all; relevance is always the model's own job.

## 4. If a Capability Needs to Influence Model Selection

Ordinary tool advertisement never requires this either. If a specific
chat Goal genuinely needs to steer Model Selection (e.g. require
tool-calling support, prefer a reasoning-capable model), supply an
explicit `Goal.metadata["execution_requirements"]` override at the
point the Goal is built (see `ai_context.goal_builder.
build_chat_goal()` for the existing example: `tool_calling="preferred"`
whenever a non-empty tool roster is offered). This is a structural
decision made once, before `Brain.handle()` is called - never a
message-text pattern match, and never a change to Planner itself. See
`model_selection/requirements.py`'s `build_execution_requirements()`
for the full override precedence.

## 5. Common Mistakes to Avoid

- **Do not** add a new regex/keyword pattern anywhere to decide
  whether your new capability's tool should be advertised for a given
  message. There is no mechanism left in AI Context Engineering that
  works that way, and adding one back would reintroduce exactly the
  scaling problem this migration removed.
- **Do not** modify `model_selection/rules.py`, `preference_rules.py`,
  `filtering.py`, or `selector.py` to special-case a new capability.
  `tool_calling` is already read generically by `ToolCallingRule`/
  `filtering.py`.
- **Do not** modify `ai_context/tool_context.py` for a new capability
  at all - it already reads `tool_affordance`/`identity_sensitive`/
  `authorization_predicate` generically from every Capability's own
  metadata; adding a capability-specific branch there would violate
  Capability Independence.
- **Do not** add capability-specific behavioral text to `ai_context/
  behavior.py` or `ai_context/reasoning_policy.py` (e.g. "only call
  `your_tool_name` when..."). That guidance belongs entirely in your
  own Tool's `use_when`/`avoid_when`/`result_semantics`/
  `failure_semantics` Tool Affordance Contract fields - see
  `parika/tools/memory/manifest.py`'s `MEMORY_TOOL_AFFORDANCES` for
  the reference example of guidance that used to be hardcoded in AI
  Context Engineering and was moved there instead.

## 6. Where to Look for Examples

- `parika/tools/filesystem/manifest.py`, `parika/tools/shell/
  manifest.py`, `parika/tools/coding/manifest.py` - the "one Tool per
  Capability" registration pattern for a multi-operation Tool.
- `parika/tools/weather/manifest.py`, `parika/tools/runtime_info/
  manifest.py` - the pattern for a Tool implementing exactly one
  Capability, including its own `*_TOOL_AFFORDANCE(S)`.
- `parika/tools/memory/manifest.py`, `parika/tools/memory/intent.py`,
  `parika/modules/memory/driver.py` - the reference example of a
  Capability supplying its own `identity_sensitive`/
  `authorization_predicate` metadata.
- `parika/interfaces/ai_context/capability_context.py` and
  `tool_context.py` - Automatic Capability Discovery and the generic
  metadata contract AI Context Engineering reads.
- `tests/interfaces/test_chat_capability.py`
  (`TestDiscoverToolSpecs`) and
  `tests/integration/test_context_assembly_pipeline.py`
  (`TestToolAdvertisementFiltering`) - live-pipeline verification that
  a new/disabled Capability is advertised/excluded correctly.
