# PARIKA AI Context Engineering

**Status:** Live, implemented, and tested. This document describes what
actually exists in the codebase today.

This is the authoritative document for **AI Context Engineering** -
the layer, living entirely in `parika/interfaces/` (before
`Brain.handle()` is ever called), responsible for constructing the
AI's runtime worldview and letting the model itself understand intent
naturally, instead of PARIKA guessing intent from regex/keyword
patterns.

This document previously described **Requirement Inference**, a
Planner-internal, pattern/regex-based heuristic framework, and
`parika/interfaces/tool_relevance.py`, an Interfaces-layer,
pattern/regex-based tool-advertisement router. **Both have been
completely removed** as part of the AI Context Engineering migration
(see §1-§3 below for why, and §8 for what replaced them). The
Intelligent Model Selection Framework
([`Model_Selection_Framework.md`](Model_Selection_Framework.md)) is
unaffected: its scoring/filtering/selection code was never modified by
either the old frameworks or this migration.

A later phase (Reasoning Policy & Tool Affordance Contract, §4.4-§4.5,
§5) improved reasoning *quality* on top of that migration: every
model-callable Tool now exposes a richer **Tool Affordance Contract**
(purpose, use/avoid guidance, requirements, result/failure semantics,
parameters) instead of a bare description/parameters pair, and the
system prompt now includes a general, capability-independent
**Reasoning Policy**. Neither reintroduces any pattern matching,
keyword routing, or capability-specific knowledge into AI Context
Engineering - see §4.1 and §10.3 for how Capability Independence is
preserved.

------------------------------------------------------------------------

# 1. The Problem This Migration Solves

PARIKA previously relied on pattern/regex-based semantic inference in
two independent places:

- **Requirement Inference** (`parika/core/planner/
  requirement_inference/`, now removed): a Planner-internal set of
  `InferenceRule` regex rules (`GreetingRule`, `CurrentDateTimeRule`,
  `LiveExternalInformationRule`, `NewsTopicRule`,
  `RecentOrFutureYearMentionRule`, `DocumentReferenceRule`) that
  guessed `tool_calling`/`information_freshness`/`capability_hints`
  from a Goal's message text, purely to influence Model Selection
  scoring.
- **Tool Relevance** (`parika/interfaces/tool_relevance.py`, now
  removed): an Interfaces-layer set of domain-specific regex patterns
  (`_WEATHER_PATTERN`, `_CURRENCY_PATTERN`, `_FILESYSTEM_PATTERN`,
  `_NEWS_PATTERN`, plus a greeting pattern) that decided which tool
  *names* were worth advertising to the model for a given turn.

Both frameworks shared the same structural flaw: **they required a new
pattern/rule every time a new semantic domain (a new Capability) was
introduced.** Adding a calendar, email, or database Capability would
have meant writing a new domain regex in `tool_relevance.py` and, for
consistent scoring, another `InferenceRule`. This does not scale, and
it duplicates work the model's own native tool-calling reasoning
already does once it can see a Capability's full description.

------------------------------------------------------------------------

# 2. Target Architecture

```text
User Request
  -> Conversation Context
  -> Memory
  -> Knowledge
  -> Runtime Context
  -> Capability Context        (AI Context Engineering, this document)
  -> Capability Affordances
  -> Intent Understanding      (the model's own native reasoning)
  -> Desired Outcome
  -> Brain
  -> Planner
  -> Execution
```

Not:

```text
User -> Regex -> Keywords -> Capability -> Execution
```

Semantic understanding of *which* Capability, if any, a message needs
now happens exactly once: inside the model itself, reasoning over the
full worldview AI Context Engineering hands it (identity, every
currently enabled Capability with its description, conversation
history, and relevant Memory/Knowledge). PARIKA never pre-guesses
intent from text a second time in Planner or in a keyword router.

------------------------------------------------------------------------

# 3. Responsibility Boundaries (read this first)

- **Planner still makes every planning decision; it still never
  performs semantic decomposition of a request into Goals.** That
  remains the caller's responsibility (see `planner.py`'s own module
  docstring). Planner never reads message text for inference anymore
  at all - not because a config flag disabled it, but because the
  mechanism that did so has been deleted.
- **No multi-Goal orchestration exists.** Tool calls for a chat turn
  are still resolved entirely by the model's own native tool-calling
  loop within a single Goal (`OllamaProviderDriver`/`chat_loop.py`,
  unchanged) - never by Planner or Brain building/threading a second
  dependent Goal.
- **`ProviderManager`, `CapabilityResolver`, `ToolManager`, `Brain`,
  `TaskManager`, `CapabilityRegistry`: zero code changes.**
- **The Intelligent Model Selection Framework's scoring/filtering/
  selection code is unmodified** (`rules.py`, `preference_rules.py`,
  `filtering.py`, `selector.py`, `config.py`, `selection_result.py`,
  `evaluation.py`). Only `requirements.py`'s `build_execution_
  requirements()` changed, and only to remove the now-deleted
  message-inference layer - the override precedence and every
  `ExecutionRequirements` field it already had are unchanged.
- **The AI Context Engineering layer never grants, denies, or bypasses
  permissions**, and never touches scope/policy enforcement. It only
  ever constructs conversation content and a tool roster; Security
  (Permission System, Policy Engine, Workspace/Filesystem/Shell Scope)
  remains exactly where it already lives, entirely untouched.

------------------------------------------------------------------------

# 4. Architecture: Automatic Capability Discovery

AI Context Engineering is now a dedicated, modular subsystem under
`parika/interfaces/ai_context/`; `parika/interfaces/chat_capability.py`
is a thin orchestration layer over it (see §10 for the full module
map). `ai_context.capability_context.discover_capabilities()` builds
the enabled-Capability list directly from `CapabilityRegistry`, applies
the read-only **Capability Catalog** retrieval/ranking pass (see §4.6),
and `ai_context.tool_context.discover_tool_specs()` converts the
retrieved subset into the tool roster advertised to the model:

```python
# ai_context/capability_context.py
def discover_capabilities(runtime, *, text="", catalog=None):
    definitions = runtime.capability_registry.find(
        category=CapabilityCategory.TOOL,
        enabled=True,
    )
    return (catalog or _default_catalog).retrieve(definitions, text=text)

# ai_context/tool_context.py
def discover_tool_specs(definitions, *, text):
    ...  # advertise each authorized definition - its own JSON Schema
         # if supplied via metadata, otherwise a permissive generic one
```

Every currently enabled TOOL-category Capability that the Capability
Catalog retrieves is advertised, every turn, with no hardcoded list of
capability names anywhere in either function. Registering a brand-new
Capability (Capability Registration + Capability Metadata + Tool
Registration + Permission Rules, if any - see §7) makes it advertisable
immediately, with zero changes to `ai_context/`, to `chat_capability.py`,
to any prompt, or to any pattern list. While the total number of
enabled TOOL-category Capabilities stays within the Catalog's budget
(`DEFAULT_BUDGET`, generous today), the Catalog is a pure ranking
pass-through and every enabled Capability is still advertised, exactly
as before the Catalog existed.

## 4.1 Capability Independence: affordances and authorization are metadata, not code

AI Context Engineering owns **zero** capability-specific knowledge --
no `WEATHER_SCHEMA`, `FILESYSTEM_SCHEMA`, `NEWS_SCHEMA`, or equivalent
hardcoded object; no `if capability == ...`/`if tool == ...` branch;
no hardcoded capability or tool list anywhere in
`parika/interfaces/ai_context/`. Every capability-specific fact is
instead read generically from that Capability's own
`CapabilityDefinition.metadata`, using three well-known, generic keys
`tool_context.discover_tool_specs()` understands without ever knowing
which Capability set them:

| Metadata key | Type | Meaning | Owned/set by |
|---|---|---|---|
| `tool_affordance` | mapping (see §4.4 for its fields, every one optional) | The Tool Affordance Contract: the model-facing tool schema, plus reasoning guidance (purpose, use/avoid, requirements, result/failure semantics). Absent fields fall back to `id.replace(".", "_")`, `CapabilityDefinition.description`, and a permissive generic parameters schema, respectively; absent reasoning-guidance fields simply contribute no section. | The Capability's own Tool, in its `manifest.py` (e.g. `parika/tools/weather/manifest.py`'s `WEATHER_TOOL_AFFORDANCES`), passed in by its own Module driver at registration (e.g. `parika/modules/weather/driver.py`). |
| `identity_sensitive` | `bool` | Exclude this Capability's tool from the roster whenever the turn is recognized as an Assistant Identity question. | The Capability's own Module driver (e.g. `parika/modules/memory/driver.py`, via `parika/tools/memory/manifest.py`'s `MEMORY_IDENTITY_SENSITIVE_CAPABILITIES`). |
| `authorization_predicate` | `Callable[[str], bool]` | An opaque, capability-owned check; AI Context Engineering calls it with the turn's message text and excludes the Capability when it returns `False`, without knowing what it checks. | The Capability's own Tool (e.g. `parika/tools/memory/intent.py`'s `has_explicit_memory_intent`), passed in by its own Module driver. |

This is the dependency direction the whole subsystem follows:

```text
Capability -> Capability Metadata -> Tool Affordance Contract
    -> AI Context Engineering -> Prompt -> Brain
```

AI Context Engineering never depends on an individual Capability;
every Capability instead hands AI Context Engineering everything it
needs, generically, through its own `CapabilityDefinition.metadata`.

`is_identity_query()` (`parika/tools/memory/identity_guard.py`,
imported directly by `tool_context.py`) is not itself
capability-specific knowledge: it is a generic "is this message
asking about the assistant's own identity" text classifier that never
mentions a capability id, tool name, or schema, and applies equally to
any current or future Capability that opts into `identity_sensitive`
-- it happens to live under `parika/tools/memory/` today (it also
protects `MemoryToolDriver` directly), not because it is
memory-specific.

## 4.2 The only filtering that remains: memory authorization gates

The Memory Capabilities are today's only consumers of
`identity_sensitive`/`authorization_predicate`, applying exactly two
fixed-scope security checks - never capability *routing*:

1. Every memory Capability (`memory.remember`, `memory.search`,
   `memory.forget`) sets `identity_sensitive=True`, excluding all
   three from the roster for a message recognized as an Assistant
   Identity question - identity questions must always be answered
   directly from Configuration/the system prompt.
2. `memory.remember` additionally sets `authorization_predicate=
   has_explicit_memory_intent`, so it is included only when that
   capability-owned check recognizes the message as an explicit
   request to remember/save/store something (Strictly Explicit
   Memory). `memory.search`/`memory.forget` set no predicate (always
   kept, since they are read-only/corrective).

Neither gate grows or needs updating when a new Capability is
registered: both are about exactly one tool family (memory), set by
that family's own Tool/Module, never about routing to a domain from
inside AI Context Engineering. This is the entire filtering surface
left in AI Context Engineering - every other enabled Capability is
always advertised in full, and relevance judgment for it is left
entirely to the model's own native tool-calling reasoning.

## 4.3 What replaced domain-keyword tool relevance

There is no successor module to `tool_relevance.py`'s domain routing:
it was deleted outright, not disabled or kept as a fallback. A
greeting, a weather question, and an unrelated question all now
receive the exact same full tool roster (minus the memory gates
above); the model itself decides, per its own tool-calling reasoning
over each Tool's own Affordance Contract (§4.4) and the general
Reasoning Policy (§4.5), whether to call anything at all.

## 4.4 The Tool Affordance Contract

The model previously only knew a Tool's `description` and
`parameters` - *what* it does and how to call it, never *when* to use
it, *when not to*, *what it requires* before it can be called, or *how
to interpret* its results and failures. `tool_context.
_compose_description()` now assembles a richer, single description
string from every optional field a Capability's own
`metadata["tool_affordance"]` supplies, in this fixed, generic order:

| Field | Rendered as | Example (Filesystem Read) |
|---|---|---|
| `description` | the base description (falls back to `CapabilityDefinition.description`) | "Reads the text content of a file." |
| `purpose` | `Purpose: ...` | "Provides access to text content already stored in a local file." |
| `use_when` | `Use when: ...` | "the user wants to see, read, or use the contents of a specific local file." |
| `avoid_when` | `Avoid when: ...` | "the content is already available from the conversation, injected Memory/Knowledge, or an earlier Tool result." |
| `requires` | `Requires: ...` | "the file path; ask the user for it if not already known." |
| `result_semantics` | `Interpreting results: ...` | "Returns the raw file contents. Present them directly unless the user asked for a summary or analysis." |
| `failure_semantics` | `On failure: ...` | "If the path does not exist or cannot be read, explain the problem in plain language... without exposing internal exception details." |
| `parameters` | the native tool-calling JSON Schema (unchanged mechanism) | `{"type": "object", "properties": {"path": ...}, "required": ["path"]}` |

Every field is optional and purely additive: a Capability that
supplies none of them (or a Capability with no `tool_affordance`
metadata at all) is still advertised exactly as before this phase -
`description`/`parameters` alone, with a permissive generic schema
when even that is absent. `tool_context.py` never validates, requires,
or special-cases any of these fields beyond rendering them generically
by name (§10.3) - the actual guidance text is written entirely by
each Tool's own `manifest.py` (e.g. `WEATHER_TOOL_AFFORDANCES`,
`MEMORY_TOOL_AFFORDANCES`, or `FilesystemOperationSpec`'s `purpose`/
`use_when`/... fields).

This is also where every Memory-specific behavioral rule that used to
be hardcoded inside AI Context Engineering's system prompt now lives:
`memory.remember`'s `use_when`/`avoid_when`/`result_semantics` fields
(`parika/tools/memory/manifest.py`) state "only call this when the
user explicitly asks..." and "never call this to store anything about
yourself" - AI Context Engineering's own `behavior.py` no longer
mentions any tool by name (see its module docstring).

## 4.5 The Reasoning Policy

`ai_context/reasoning_policy.py` owns a second, complementary piece:
a fixed, general, capability-independent paragraph appended to the
system prompt, stating the *order* in which the model should prefer
already-available sources over calling any Tool at all - Assistant
Identity, then the current conversation, then injected Memory, then
injected Knowledge, then an earlier Tool result, and only then a Tool
call. It never names a specific Capability or tool (§10.3); it is the
generic frame each Tool's own Affordance Contract (§4.4) is read
within, not a substitute for one. See `reasoning_policy.py`'s module
docstring for the exact text and why "Memory"/"Knowledge" there are
Core subsystem names, not Capability Registry entries.

## 4.6 The Capability Catalog: a read-only retrieval layer, not a router

`parika.core.capability_catalog.CapabilityCatalog` sits between
`discover_capabilities()`'s registry lookup and `tool_context.
discover_tool_specs()`'s tool-schema construction. It exists to solve
one scaling problem: as PARIKA's catalog of registered Capabilities
grows toward the hundreds or thousands, advertising every enabled
TOOL-category Capability every turn (as §4 always has) eventually
dominates prompt size and degrades routing accuracy. The Catalog is
**not** another planner, router, model, registry, resolver, or
execution layer -- it never executes anything, never chooses a
provider or model, never invokes a tool, and never replaces
`CapabilityRegistry` or `CapabilityResolver`. It is purely a read-only
retrieval/ranking projection over data `CapabilityRegistry` already
holds.

The Catalog is an **information-retrieval engine followed by a
ranking engine**, not a sorter that only trims when a fixed count is
exceeded. Dynamic Relevance Cutoff -- not the budget -- is what
decides *how many* capabilities are genuinely relevant to a given
turn: a narrow query ("what's the weather?") naturally survives cutoff
with only 2-3 capabilities; a broad, genuinely multi-domain request
("check the weather, convert some currency, search the web, and
summarize this PDF") naturally survives with a double-digit set
spanning every topic actually mentioned. The Budget Safety Ceiling
only ever protects against an unusually large genuinely-relevant set
turning into prompt explosion; it is not the mechanism that determines
relevance, and in the common case never triggers.

Pipeline (`parika/core/capability_catalog/`):

```text
Candidates (CapabilityRegistry.find(category=TOOL, enabled=True))
    -> Deterministic Filtering      (deterministic_filter.py)
    -> Lexical Retrieval            (lexical_retrieval.py)
    -> [Semantic Retrieval]         (semantic_retrieval.py, extension point only)
    -> Capability Family Retrieval  (family_ranking.py)
    -> Capability Retrieval         (capability_ranking.compute_combined_scores())
    -> Dynamic Relevance Cutoff     (relevance_cutoff.py)
    -> Capability Ranking           (capability_ranking.rank_capabilities())
    -> Budget Safety Ceiling        (budget_selector.py)
    -> [extra_stages]               (caller-supplied, optional)
```

Each stage's actual algorithm lives in its own pure, dependency-free
function module (as listed above); `stages.py` adapts each one into a
`PipelineStage` (`retrieval_context.py`). `CapabilityCatalog` assembles
the fixed stage sequence exactly once, in `_build_stages()`, and `retrieve()`
just iterates over it -- this is what keeps `CapabilityCatalog` a
short, flat sequencer instead of a growing monolith as stages are
added: a future *built-in* stage is one more line in `_build_stages()`,
and a caller-supplied stage (e.g. an experimental re-ranker that does
not yet warrant a dedicated constructor parameter) can be appended via
the public `extra_stages` constructor parameter without touching this
package's source at all.

- **Deterministic Filtering** removes capabilities that cannot possibly
  be selected this turn: disabled (`enabled=False`), internal
  (`public=False`), or explicitly opted out
  (`metadata["catalog_excluded"]`), plus any capability-owned
  `metadata["compatibility_predicate"]` check (e.g. incompatible
  runtime state). Purely deterministic; no ranking happens here.
- **Lexical Retrieval** scores each surviving candidate against the
  turn's text using only that capability's own generic discovery
  fields: `name`, `description`, `tags`, `aliases`, `keywords`,
  `examples` (all new, optional, backward-compatible
  `CapabilityDefinition` fields -- see §4.7). The default strategy
  (`lexical_retrieval._field_weighted_idf_scores()`) is a **field-
  weighted, IDF-weighted token-overlap score**, never regex/pattern-
  based intent routing:
  - **Field weighting**: a token found in a capability's own `name`/
    `aliases` (its stated identity) counts for more than the same
    token only appearing in free-form `description`/`examples` prose;
    `tags`/`keywords` sit in between. This is what lets a query like
    "current weather" correctly favor `weather.current` (whose *name*
    is literally "Weather Current") over an unrelated capability that
    merely mentions "current" once in passing prose (e.g. "...using
    the current exchange rate").
  - **Inverse document frequency (IDF)**: a query token shared by many
    of *this turn's own candidates*' discovery text contributes
    proportionally less to each of their scores than a token unique or
    near-unique to one candidate -- computed fresh from the current
    candidate batch every call, never a fixed/precomputed list.
  - **Stopword removal + light singularization**: both the query and
    every candidate's discovery text pass through a generic English
    stopword list (removing function words like "from"/"the"/"is")
    and a conservative plural-to-singular normalizer (e.g. "emails" ->
    "email"), so an inflected form in the query still matches a
    capability's discovery text using a different one.

  Every score is clamped to the canonical `[0.0, 1.0]` range. The
  scoring strategy is pluggable: `score_candidates()` only falls back
  to the `LexicalScorer` `Protocol` (`TokenOverlapScorer` is the
  simpler, corpus-independent alternative it ships) when a caller
  explicitly supplies a `scorer` override, so an entirely different
  strategy can still be substituted without changing the Catalog's
  public API.
- **Semantic Retrieval** is an intentionally unimplemented extension
  point (`SemanticScorer` `Protocol` in `semantic_retrieval.py`). No
  embedding-based retrieval ships today; when a `CapabilityCatalog` is
  constructed without one (the default), this stage contributes
  nothing. A future implementation must also return scores in
  `[0.0, 1.0]`, so lexical and semantic scores stay directly
  comparable and can be combined by simple addition, with neither
  source able to dominate the other purely due to differing scales.
- **Capability Family Retrieval** groups already-scored candidates by
  their retrieval **Capability Family** (`family_ranking.py`, using
  each capability's own `family` field, or -- since almost no Module
  populates that newer field yet -- its own already-populated `tags`,
  preferring the tag that is *least common across this turn's own
  candidate set* over a broadly shared, generic one; see §4.7) and
  ranks each family primarily by its best member's score (max-pooling,
  not an average -- a large family of weakly related members must
  never dilute one genuinely strong match from a sibling), plus a
  small, capped tie-break bonus for the number of distinct members
  that matched at all.
- **Capability Retrieval** combines each capability's own score with a
  small boost from its family's rank score into one combined relevance
  score per capability -- the single number Dynamic Relevance Cutoff
  and the final Capability Ranking stage both reason about from this
  point on.
- **Dynamic Relevance Cutoff** is what actually decides *how many*
  capabilities are relevant this turn -- see the design note below.
  Runs strictly before Capability Ranking and the Budget Safety
  Ceiling.
- **Capability Ranking** orders cutoff's *already-relevant* survivors
  by their combined score, producing a fully ordered tuple of leaf
  `CapabilityDefinition`s (never a family -- families are discarded
  after Capability Retrieval). It never decides relevance itself.
- **Budget Safety Ceiling** truncates the ranked tuple to at most
  `budget` capabilities (`DEFAULT_BUDGET`, currently 300; a non-
  positive budget means unbounded) -- a safeguard against prompt
  explosion, never the retrieval algorithm. In the common case cutoff
  has already narrowed the roster well under budget, so this stage is
  a no-op. `DEFAULT_BUDGET` was raised from 150 to 300 when the Video
  Module's thirty additional TOOL Capabilities brought the enabled
  TOOL-category roster to 151 -- above the old ceiling -- which
  silently truncated one Capability off a no-lexical-signal turn's
  full-roster deferral for the first time; this is a ceiling
  adjustment to preserve the "essentially never triggers at current
  catalog size" property below, not a new mechanism.

Capability Families are a **retrieval boundary**, distinct from
Modules (an **implementation boundary**): a family only groups related
leaf capabilities for ranking (e.g. `document` grouping
`document.summarize`/`document.search`/`document.translate`); it is
never executable, never a Module, never a Planner, and the router
always receives leaf capabilities, never a family.

### Dynamic Relevance Cutoff: a two-level hybrid, not a fixed count

`relevance_cutoff.py` implements a provider-independent, two-level
hybrid of **relative thresholding** and **score-gap ("elbow")
detection**:

1. **Family admission** first decides *which topics are even in play*
   this turn, comparing each family's own best score against the
   *overall* best family score, using a deliberately lenient relative
   threshold (`_FAMILY_ADMISSION_RELATIVE_THRESHOLD`, no gap
   detection). This is what correctly handles a genuinely broad,
   multi-domain request: Weather, Currency, and Document may each have
   a different *natural* best score purely because their own discovery
   text differs in richness, so admitting families independently --
   rather than comparing every individual capability only against the
   single globally-highest-scoring capability -- avoids unfairly
   discarding an entire legitimately-relevant topic just because
   another topic happened to score higher in absolute terms.
2. **Within-family member selection** then applies the *same* hybrid
   cutoff a second time, scoped to each *admitted* family's own
   members and their own combined scores, using the stricter
   `_RELATIVE_THRESHOLD` plus score-gap detection. This is what lets a
   narrow, single-topic query cut sharply down to just its 2-3 true
   matches within that one family, while a family that is itself broad
   keeps every one of its naturally-clustered members instead of being
   truncated to an arbitrary count.

The critical exception -- and the reason this stage never needs any
capability-specific knowledge -- is when **no** candidate scored above
zero at all: this means the turn's text carried no lexical (or
semantic) signal whatsoever, not that every capability is equally
irrelevant. Cutoff is skipped entirely in that case and every
deterministically-filtered candidate survives, deferring to the
model's own tool-calling reasoning exactly as Automatic Capability
Discovery has always done for an ambiguous/generic turn (a greeting,
an identity question) -- see the greeting/identity tests in
`tests/integration/test_context_assembly_pipeline.py::
TestToolAdvertisementFiltering`.

Known limitation: lexical-only matching can occasionally produce a
narrow, coincidental match (e.g. an unrelated sentence sharing one
uncommon word with exactly one capability's description) that Dynamic
Relevance Cutoff then treats as a genuine signal. This is an inherent
limitation of *lexical* retrieval, not a cutoff design flaw -- the
`SemanticScorer` extension point exists precisely to let a future
embedding-based signal disambiguate cases lexical overlap cannot (see
§4.6's Semantic Retrieval stage above).

## 4.7 New `CapabilityDefinition` metadata fields

Five new fields were added to `CapabilityDefinition`
(`parika/core/capability_registry/capability_definition.py`), all
optional and defaulted, so every existing `CapabilityDefinition(...)`
call site continues to work unchanged:

| Field | Type | Default | Used by |
|---|---|---|---|
| `public` | `bool` | `True` | Deterministic Filtering -- set `False` for a capability that must never be advertised to a router/chat model. |
| `family` | `str \| None` | `None` | Capability Family Retrieval -- an explicit retrieval-grouping id; falls back to the capability's own least-common `tags` value (see `capability_family.resolve_family_ids()`), then a category-derived id, when absent. |
| `aliases` | `frozenset[str]` | `frozenset()` | Lexical Retrieval -- alternative names contributing discovery tokens. |
| `keywords` | `frozenset[str]` | `frozenset()` | Lexical Retrieval -- free-form retrieval keywords, distinct from `tags` (which remain a `CapabilityRegistry` exact-lookup index). |
| `examples` | `tuple[str, ...]` | `()` | Lexical Retrieval -- example request phrasings this capability satisfies. |

These are additive metadata only; they do not change
`CapabilityRegistry`'s or `CapabilityResolver`'s responsibilities (see
§9/§10 below), and a Capability that sets none of them behaves exactly
as it did before these fields existed.

## 4.8 Future metadata extension points (documented, not implemented)

The fields in §4.7 are sufficient for every retrieval stage the
Capability Catalog implements today. The following were considered
and deliberately **not** added as dedicated `CapabilityDefinition`
fields, since no current stage needs them and adding metadata nobody
reads yet would be unnecessary complexity:

| Possible future field | Would serve | Why not added yet |
|---|---|---|
| `supported_modalities` / `supported_artifacts` | A dedicated Deterministic Filtering check for modality/artifact compatibility | `metadata["compatibility_predicate"]` (§ Deterministic Filtering above) already covers this generically today, as a capability-owned callable; a dedicated field would only be worth adding once several Capabilities need the *same* structured modality/artifact vocabulary rather than an opaque predicate. |
| `side_effects` | Ranking capabilities with side effects differently from read-only ones | No retrieval stage currently distinguishes side-effecting from read-only capabilities; Planner/PolicyEngine, not the Catalog, are the correct owners if this is ever needed for anything beyond retrieval. |
| `discovery_text` (a single pre-composed/pre-tokenized field) | A minor performance optimization for Lexical Retrieval, avoiding re-tokenizing `name`/`description`/`tags`/`aliases`/`keywords`/`examples` on every call | Premature: today's catalog size makes this a non-issue; revisit only if profiling shows tokenization cost matters at a much larger catalog size. |
| `embedding_vector` (or similar) | Feeding a future `SemanticScorer` without needing to embed text on every request | Belongs to whatever concrete `SemanticScorer` implementation eventually ships (see §4.6's Semantic Retrieval stage) -- adding it speculatively now, before any implementation exists to consume it, would be exactly the kind of premature abstraction this Catalog's design explicitly avoids. |
| `weight` / `priority` (manual ranking override) | Letting a Capability's own Module force it higher/lower in ranking regardless of retrieval score | Not implemented: would let individual Capabilities silently override the Catalog's ranking logic, working against Capability Independence (§4.1) and Automatic Capability Discovery (§4) by reintroducing per-capability special-casing at the metadata level. If ever justified, it should be scoped narrowly and reviewed on its own, not added preemptively. |

## 4.9 Observability: the Capability Catalog produces no log output

An earlier development iteration of the Capability Catalog logged
every stage's decision at DEBUG level (received candidate count,
per-candidate lexical/semantic/combined scores, family ranks, the
Dynamic Relevance Cutoff decision, the ranked list, and the final
advertised roster) to make the new retrieval pipeline observable while
it was being built and tuned. That logging has been **removed in
full** now that the pipeline is considered stable: no module under
`parika/core/capability_catalog/` imports `logging` or holds a logger
at all, `CapabilityCatalog.__init__()` takes no `logger` parameter,
and no `PipelineStage` (`stages.py`) logs anything. `retrieve()` is a
pure function of `(definitions, text)` with zero side effects.

This is a deliberate production posture, not an oversight: the
Capability Catalog runs on every single chat turn, and per-candidate
logging over the full candidate set on every turn is exactly the kind
of always-on verbosity PARIKA's logging framework is not meant to
carry by default. Nothing about PARIKA's logging framework itself
(`parika.core.logger.logger.Logger`) changed -- every other Core
component still logs exactly as it always has; this section only
documents that the Capability Catalog specifically does not.

------------------------------------------------------------------------

# 5. Capability Metadata and Affordances

The AI's worldview is built from data already present on registered
Capabilities/Tools - `CapabilityDefinition.description` and each
Capability's own Tool Affordance Contract (§4.4), composed into
`OllamaToolSpec.description` - never from a capability id like
`filesystem.write` or `weather.current` in isolation. For example, the
Filesystem Tool's operations each carry a plain-language description
plus purpose/use-and-avoid/requirement/result/failure guidance
("Reads the text content of a file." + "Purpose: Provides access to
text content already stored in a local file." + "Use when: ..." +
...) that the model reads directly as part of the tools array, exactly
like any other native tool-calling schema. No separate "affordance"
document or prompt section is generated or maintained by hand: the
guidance that already exists on each Tool's own manifest is the same
text that gives the model its understanding of what a Capability lets
it do, when to use it, and how to interpret it.

------------------------------------------------------------------------

# 6. Model Selection: `ExecutionRequirements` Without Message Inference

`model_selection/requirements.py`'s `build_execution_requirements()`
now has two layers, highest precedence first:

1. **Explicit `Goal.metadata["execution_requirements"]` override.** A
   full `ExecutionRequirements` instance is trusted completely, or a
   partial dict overrides only the keys it sets.
2. **Category-derived defaults** (unchanged from the Model Selection
   Framework: `REASONING`/`PLANNING` -> `COMPLEX` reasoning level,
   etc.).

The former, intermediate "Requirement Inference" layer - reading
`Goal.inputs["message"]` through regex rules - has been deleted, along
with `[planning.requirement_inference]` configuration and the
`parika/core/planner/requirement_inference/` package in its entirety.
A caller that needs a specific requirement now supplies it directly.

## 6.1 The Interfaces layer's part

`ai_context.goal_builder.build_chat_goal()` (orchestrated by
`chat_capability.build_chat_goal()`) supplies Planner's override
itself, but only from **structural** facts about the request being
built - never from pattern-matching the message text:

```python
execution_requirements = {"streaming_required": on_token is not None}
if tools:
    execution_requirements["tool_calling"] = "preferred"
```

`tool_calling="preferred"` is set whenever a non-empty tool roster is
being offered for this turn - a fact AI Context Engineering already
knows structurally, since it just built that roster via
`ai_context.tool_context.discover_tool_specs()` - never derived from
what the message says. `latest_message` is still threaded into
`Goal.inputs["message"]` for observability/diagnostics only; no
Planner code reads it for inference anymore.

------------------------------------------------------------------------

# 7. Capability Discovery Checklist

After this migration, adding a new capability requires only:

1. **Capability Registration** - register a `CapabilityDefinition`
   (id, name, description, category) with `CapabilityRegistry`, as
   already required for any Capability.
2. **Capability Metadata** - a clear, plain-language `description`
   (this doubles as the AI's affordance description - see §5).
3. **Tool Registration** - register a `Tool` with `ToolManager` (for a
   TOOL-category Capability), following the existing "one Tool per
   Capability" pattern already used by Filesystem/Shell/Coding/News/
   Weather/Currency.
4. **Tool Affordance Contract** (optional, recommended) - a
   `metadata["tool_affordance"]` mapping with any subset of
   `name`/`description`/`purpose`/`use_when`/`avoid_when`/`requires`/
   `result_semantics`/`failure_semantics`/`parameters` (§4.4), so the
   model reasons about *when* to use the new Capability, not just
   *what* it does. Omitting this entirely still works - the
   Capability is still advertised, with `CapabilityDefinition.
   description` and a permissive generic parameters schema.
5. **Permission Rules** - only if the new Capability needs one (no
   change to the Permission System itself).

None of the following ever need to change: AI Context Engineering
code (`chat_capability.py` or any `ai_context/` module), any prompt
builder, any semantic rule, or any pattern list.
`ai_context.capability_context.discover_capabilities()`/
`ai_context.tool_context.discover_tool_specs()` pick up the new
Capability - and its Tool Affordance Contract, if it supplies one -
automatically the moment it is registered and enabled.

------------------------------------------------------------------------

# 8. What Was Removed, and Why It Is Not a Regression

| Removed | Was for | Replaced by |
|---|---|---|
| `parika/core/planner/requirement_inference/` (rules.py, resolver.py, hints.py, config.py) | Guessing `tool_calling`/`information_freshness`/`capability_hints` from message text via regex, purely to influence Model Selection scoring | An explicit, structural `Goal.metadata["execution_requirements"]` override from AI Context Engineering (§6.1); Model Selection's own scoring rules are unaffected either way, since `NOT_NEEDED`/`PREFERRED` never hard-exclude a candidate |
| `parika/interfaces/tool_relevance.py`'s domain patterns (`_WEATHER_PATTERN`, `_CURRENCY_PATTERN`, `_FILESYSTEM_PATTERN`, `_NEWS_PATTERN`) and greeting suppression | Deciding which tool names to advertise per message, to reduce hallucinated tool calls | Advertising every enabled Capability every turn (Automatic Capability Discovery) and trusting the model's own native tool-calling reasoning over each tool's description, which is at least as effective at avoiding an irrelevant call and requires zero maintenance as new Capabilities are added |
| `[planning.requirement_inference]` configuration | Kill switch for Requirement Inference | No longer needed - there is nothing left to disable |

| `parika/interfaces/chat_capability.py`'s hardcoded `WEB_SEARCH_TOOL_SPEC`/`RUNTIME_DATETIME_TOOL_SPEC`/`FILESYSTEM_TOOL_SPECS`/`WEATHER_*_TOOL_SPEC`/`CURRENCY_*_TOOL_SPEC`/`NEWS_*_TOOL_SPEC`/`MEMORY_*_TOOL_SPEC` constants and `known_by_capability_id` lookup table | Every capability's model-facing tool schema, hardcoded inside AI Context Engineering itself | Each Tool's own `*_TOOL_AFFORDANCE(S)` constant in its own `manifest.py` (e.g. `parika/tools/weather/manifest.py`'s `WEATHER_TOOL_AFFORDANCES`), registered as `CapabilityDefinition.metadata["tool_affordance"]` by that Tool's own Module driver, discovered generically by `ai_context.tool_context.discover_tool_specs()` (§4.1/§4.4) |
| `parika/interfaces/memory_intent.py` | Detecting explicit memory-write intent - meaningful only for `memory.remember`, i.e. capability-specific knowledge | `parika/tools/memory/intent.py` (`has_explicit_memory_intent`), registered as `memory.remember`'s own `CapabilityDefinition.metadata["authorization_predicate"]` (§4.1/§4.2) |
| `ai_context/behavior.py`'s memory-specific instructions (e.g. "only call `memory_remember` when the user explicitly asks...", "never call `memory_remember` to store your own identity...") | Telling the model, inside AI Context Engineering's own system prompt, exactly when to use one specific Capability's tools - i.e. "Memory rules... inside AI Context Engineering", explicitly forbidden by Capability Independence | `memory.remember`'s own `use_when`/`avoid_when`/`result_semantics` Tool Affordance Contract fields (`parika/tools/memory/manifest.py`'s `MEMORY_TOOL_AFFORDANCES`), composed into its advertised description generically by `tool_context.py` (§4.4) |

What was **kept**, deliberately, because it is not capability/domain
routing and does not grow when a new Capability is registered:

- `is_identity_query()` (`tools/memory/identity_guard.py`) - a generic
  "is this an identity question" text classifier, consulted by
  `ai_context.tool_context.discover_tool_specs()` for every
  `identity_sensitive` Capability, never mentioning any capability by
  name (§4.1).
- `interfaces/session_intent.py` - a fixed, single-purpose detector for
  "give me previously saved session content", unrelated to Capability
  discovery.
- `interfaces/preference_detection.py` - a fixed, single-purpose
  detector used only for durable Memory record extraction on session
  save.
- `tools/memory/categorization.py` - classifies the *content* of a
  memory already explicitly authorized for storage, not a routing
  decision.

------------------------------------------------------------------------

# 9. Backward Compatibility / Migration Notes

- `Planner.__init__` lost the `inference_rules` optional keyword
  parameter it previously gained; no other call site is affected,
  since it was optional and rarely supplied.
- `model_selection.build_execution_requirements()` lost its
  `inference_enabled`/`inference_rules` optional keyword parameters.
  Every other parameter and the override-precedence contract are
  unchanged.
- A Goal with no explicit `execution_requirements` override now
  receives the plain category default (previously, it could also
  receive an inferred value from its message text). This is not
  observable as a behavior regression for chat turns built through
  `chat_capability.build_chat_goal()`, since that function already
  supplies its own `tool_calling` override (§6.1); `ToolCallingRule`'s
  own scoring never hard-excludes a `NOT_NEEDED`/`PREFERRED` candidate
  either way (see `model_selection/filtering.py`).
- `tests/core/planner/requirement_inference/`,
  `tests/core/planner/test_planner_requirement_inference.py`, and
  `tests/interfaces/test_tool_relevance.py` were removed along with
  the code they tested.
- `parika/interfaces/chat_capability.py`'s `discover_tool_specs()`
  gained a required `text` keyword argument (it now also applies the
  memory-authorization gates in one step) and lost its
  `gate_memory_authorization()` companion function and every
  `*_TOOL_SPEC`/`*_TOOL_SPECS` constant - see §10 for where each
  responsibility moved. `tests/interfaces/test_memory_intent.py` moved
  to `tests/tools/memory/test_intent.py` alongside the relocated
  module. See `tests/interfaces/test_chat_capability.py` and
  `tests/integration/test_context_assembly_pipeline.py`
  (`TestToolAdvertisementFiltering`) for the current live-pipeline
  coverage.
- Every Tool's `metadata["tool_schema"]` key/constant was renamed to
  `metadata["tool_affordance"]`/`*_TOOL_AFFORDANCE(S)` when the Tool
  Affordance Contract (§4.4) replaced the plain description/parameters
  schema. `tool_context._build_tool_spec()`'s composed `description`
  now includes the Tool's affordance sections (e.g. `Use when: ...`)
  in addition to its base description - any code or test comparing a
  full `OllamaToolSpec` for equality (rather than by `capability_id`,
  `name`, or `parameters`) needs to account for this (see
  `tests/interfaces/test_chat_capability.py::TestDiscoverToolSpecs::
  test_includes_web_search_with_its_own_affordance_contract`).
- `ai_context/behavior.py`'s system-prompt text no longer mentions
  `memory_remember`/`memory_search` or describes Strictly Explicit
  Memory behavior - that guidance moved into `memory.remember`'s own
  Tool Affordance Contract (§4.4, §8). A new `ai_context/
  reasoning_policy.py` module and its `REASONING_POLICY` text were
  added to the system prompt; `prompt_builder.
  build_assistant_system_prompt()`'s composed output text changed
  accordingly (see `tests/interfaces/test_chat_capability.py::
  TestBuildAssistantSystemPrompt`).

------------------------------------------------------------------------

# 10. AI Context Engineering Module Structure

`parika/interfaces/chat_capability.py` is a thin orchestration layer;
every function it exposes delegates to exactly one module under
`parika/interfaces/ai_context/`, each owning exactly one
responsibility:

```text
parika/interfaces/
├── chat_capability.py        Thin orchestration layer (no implementation logic)
└── ai_context/
    ├── __init__.py           Package overview and Capability Independence rule
    ├── identity.py            Assistant identity text only
    ├── behavior.py             Fixed behavioral operating instructions only
    │                          (capability-independent - see its module docstring)
    ├── constraints.py          General constraint text only (currently none)
    ├── reasoning_policy.py      General, capability-independent source-preference
    │                          ordering only (§4.5) - never names a Capability
    ├── model_selection_policy.py General, capability-independent policy describing
    │                          the optional, reserved `model_selection_hint`
    │                          tool-call argument (§11) - never names a
    │                          Capability, tool, model, or task
    ├── prompt_builder.py       Combines identity/behavior/constraints/
    │                          reasoning_policy/model_selection_policy -> system prompt
    ├── conversation.py         Splices retrieved context into the message list
    ├── memory.py               Renders an already-retrieved Memory result set
    ├── knowledge.py             Renders an already-retrieved Knowledge result set
    ├── context_builder.py       Calls Brain.assemble_context(), renders via memory.py/knowledge.py
    ├── session_context.py       Retrieves/renders saved-session excerpts (explicit intent only)
    ├── capability_context.py    Discovers enabled Capabilities from CapabilityRegistry
    │                          and applies the Capability Catalog retrieval/ranking
    │                          pass (§4.6, `parika.core.capability_catalog`)
    ├── tool_context.py          Builds tool specs, composing each Capability's own
    │                          Tool Affordance Contract (§4.4) into its description,
    │                          and applies the metadata-driven authorization gates
    ├── worker_inventory.py      Renders the compact Worker Model Inventory (§11),
    │                          strictly separating objective provider facts from
    │                          PARIKA Model Knowledge - never selects a model itself
    └── goal_builder.py          Builds the Goal handed to Brain, and injects the
                               Worker Model Inventory once Planner has selected
                               this Goal's own routing model (§11)
```

## 10.1 Orchestration pipeline

`InterfaceSession._submit_text()` (`parika/interfaces/session.py`)
drives the pipeline every turn, calling only `chat_capability.py`'s
thin public functions:

```text
build_assistant_system_prompt()     (session construction time only)
    -> ai_context.prompt_builder
        -> ai_context.identity + ai_context.behavior
           + ai_context.constraints + ai_context.reasoning_policy
           + ai_context.model_selection_policy (§11)
discover_tool_specs(runtime, text=text)
    -> ai_context.capability_context.discover_capabilities(runtime, text=text)
        -> CapabilityRegistry.find(category=TOOL, enabled=True)
        -> capability_catalog.CapabilityCatalog.retrieve() (§4.6)
    -> ai_context.tool_context.discover_tool_specs()
        (composes each Capability's own Tool Affordance Contract, §4.4)
assemble_context_messages()
    -> ai_context.context_builder
        -> ai_context.memory + ai_context.knowledge
assemble_session_retrieval_messages()
    -> ai_context.session_context
assemble_conversation_messages()
    -> ai_context.conversation
build_chat_goal(..., runtime=runtime)
    -> ai_context.goal_builder
        -> renders ai_context.worker_inventory (§11) inside
           provider_request_builder, once Planner has already
           selected the routing model - no separate step here
Brain.handle()
```

## 10.2 Dependency direction

```text
Capability
    -> Capability Metadata (tool_affordance / identity_sensitive / authorization_predicate)
        -> Tool Affordance Contract
            -> AI Context Engineering (ai_context/*)
                -> Prompt / Goal
                    -> Brain
```

No arrow points the other way: no `ai_context` module imports a
specific Tool/Module's driver, manifest constant, or capability id
(the sole, deliberate exception is `identity_guard.is_identity_query()`
-- generic infrastructure, not capability-specific knowledge; see
§4.1). `reasoning_policy.py` sits entirely inside `ai_context/*` in
this diagram - it is capability-independent text authored by AI
Context Engineering itself, consumed only by `prompt_builder.py`, and
never a source of capability-specific knowledge (§4.5). Security
(Permission System, Policy Engine, Workspace/Filesystem/Shell Scope,
Authentication, Authorization) sits entirely outside this diagram and
is never touched by it.

## 10.3 Confirming Capability Independence

Every capability-specific fact AI Context Engineering needs is read
through exactly three generic `CapabilityDefinition.metadata` keys
(§4.1: `tool_affordance`, `identity_sensitive`,
`authorization_predicate`). `grep`-verifiable: no file under
`parika/interfaces/ai_context/` contains a capability id literal (e.g.
`"weather."`, `"filesystem."`, `"news."`, `"currency."`, `"memory."`),
a tool name literal (e.g. `"weather_current"`), or an `if`/`match`
branch keyed on one - including `reasoning_policy.py`'s
`REASONING_POLICY` text and `behavior.py`'s `BEHAVIOR_INSTRUCTIONS`
text, both of which are capability-independent by construction (see
each module's own docstring for what was deliberately moved out of
them into a Tool's own Affordance Contract instead).

## 10.4 Confirming every Tool owns its own Affordance Contract

Every Tool that supplies a curated contract defines it in its own
`manifest.py`, alongside the `Tool` descriptors it already owned:
`WEB_SEARCH_TOOL_AFFORDANCE` (`tools/web_search/manifest.py`),
`RUNTIME_INFO_TOOL_AFFORDANCE` (`tools/runtime_info/manifest.py`),
`FilesystemOperationSpec`'s `purpose`/`use_when`/`avoid_when`/
`requires`/`result_semantics`/`failure_semantics`/`parameters` fields
(`tools/filesystem/manifest.py`), `WEATHER_TOOL_AFFORDANCES`
(`tools/weather/manifest.py`), `CURRENCY_TOOL_AFFORDANCES`
(`tools/currency/manifest.py`), `NEWS_TOOL_AFFORDANCES`
(`tools/news/manifest.py`), and `MEMORY_TOOL_AFFORDANCES`
(`tools/memory/manifest.py`). Each Tool's own Module driver passes its
contract into `CapabilityDefinition.metadata["tool_affordance"]` at
registration - AI Context Engineering never defines, edits, or
duplicates any of these contracts; it only ever reads them back
generically (§4.1, §4.4).

------------------------------------------------------------------------

# 11. AI-Assisted Model Selection Refinement

AI Context Engineering owns the two new, per-turn inputs an
AI-assisted routing model needs to recommend candidate worker models
and downstream execution requirements (see
[`Model_Selection_Framework.md`](Model_Selection_Framework.md) §13 for
the full mechanics; this section covers only this package's own part).

**`worker_inventory.py`** renders a compact, semantic inventory of
other installed models, built entirely from `ProviderManager.get_all()`
- no additional provider API call. It is invoked from inside
`goal_builder.build_chat_goal()`'s own `provider_request_builder`
closure, which Planner calls only *after* it has already selected this
turn's routing model - so the inventory can exclude exactly that model
with no second selection pass, no dry run, and no duplicated
filtering/scoring logic (§3a/§6 remain entirely Planner's).
`build_chat_goal()`'s new `provider_manager` parameter defaults to
`None`, which skips this entirely - `InterfaceSession._submit_text()`
(`session.py`) is the only caller that passes one today, via
`chat_capability.build_chat_goal(..., runtime=self._runtime)`.

**`model_selection_policy.py`** is the generic, capability-independent
instruction (composed into the system prompt by `prompt_builder.py`,
alongside `reasoning_policy.py`) telling the routing model it may
optionally include a `model_selection_hint` argument on any tool call
whose execution will be delegated to a specialized model. Exactly like
`reasoning_policy.py` (§4.5), it never names a specific Capability,
tool, model, or task.

Everything downstream of the tool call itself -
`ToolCallResolver`'s extraction, the two-step Tool drivers' one-line
forwarding, `RoutingRecommendationRule` - lives outside AI Context
Engineering and is documented in
[`Model_Selection_Framework.md`](Model_Selection_Framework.md) §13 and
[`Provider_Tool_Calling.md`](Provider_Tool_Calling.md).

This is purely additive to everything described in §1-§10 above:
Automatic Capability Discovery, the Tool Affordance Contract, and
`ExecutionRequirements`'s existing override mechanism (§6) are entirely
unmodified. `candidate_models` is deliberately not placed alongside
`tool_calling`/`streaming_required` as a first-class
`ExecutionRequirements` override field - see
`Model_Selection_Framework.md` §6.3 for why a recommendation is
carried under `ExecutionRequirements.metadata` instead.
