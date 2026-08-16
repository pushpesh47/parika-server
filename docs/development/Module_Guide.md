
# PARIKA Module Guide

**Status:** Authoritative guide for developing PARIKA Modules.

> This document replaces **Modules.md** and **Module_Development_Guide.md**. It is the single source of truth for Module development.

---

# 1. Purpose

**When to read this:** use this guide when creating or extending a PARIKA module.

**Related documents:** [../architecture/PARIKA_Architecture_Specification_v1.0.md](../architecture/PARIKA_Architecture_Specification_v1.0.md), [Capability_Guide.md](Capability_Guide.md), and [Tool_Guide.md](Tool_Guide.md).

A Module extends PARIKA by adding new capabilities without modifying the frozen Core.

This guide describes:

- Module architecture
- Package layout
- Manifest
- Module lifecycle
- ModuleDriver
- Registration
- Configuration
- EventBus integration
- Permissions
- Health checks
- Dependencies
- Testing
- Packaging
- Best practices

Architecture details that apply to the entire system are intentionally not duplicated here. Refer to the Architecture Specification and Core Component Responsibilities.

---

# 2. Architecture

Every Module provides:

- ModuleManifest
- ModuleDriver
- One or more declared CapabilityDefinitions
- Optional Tool registrations
- Optional Provider registrations
- Optional EventBus subscriptions
- Optional HealthManager registration

A Module never:

- modifies Core components
- communicates directly with another Module
- owns configuration
- bypasses CapabilityRegistry or ToolManager
- instantiates Core managers

All interaction happens through frozen Core APIs.

---

# 3. Package Layout

```text
parika/modules/<module_id>/
├── __init__.py
├── manifest.py
└── driver.py
```

Additional files may be added when required.

---

# 4. Manifest

The manifest contains metadata only.

Typical fields include:

- id
- name
- version
- description
- author
- license
- tags
- dependencies
- required_capabilities
- required_permissions
- driver
- configuration_schema
- metadata

Behavior never belongs in the manifest.

---

# 5. Module Lifecycle

```text
register()
      ↓
INACTIVE
      ↓
load()
      ↓
driver.start()
      ↓
ACTIVE
      ↓
unload()
      ↓
driver.stop()
      ↓
INACTIVE
      ↓
unregister()
```

ModuleManager owns the lifecycle.

The ModuleDriver only performs startup and shutdown work.

---

# 6. ModuleDriver

The ModuleDriver is responsible for:

- registering capabilities
- registering tools
- registering providers
- subscribing to events
- registering health checks
- releasing resources during shutdown

Business logic belongs inside ToolDrivers or ProviderDrivers, not inside the ModuleDriver.

---

# 7. Registration Rules

During start():

- register capabilities
- register tools/providers
- subscribe to events
- register health checks

During stop():

- unregister everything
- perform cleanup
- unregister in reverse order

Startup and shutdown must always be symmetrical.

---

# 8. EventBus

Subscribe in start().

Unsubscribe in stop().

Never communicate directly with another Module.

---

# 9. Configuration

Modules receive Configuration through dependency injection.

Configuration is read-only.

Modules never own configuration values.

---

# 10. Permissions

Declare required permissions in the manifest.

PermissionManager performs enforcement.

Never assume declared permissions are automatically granted.

---

# 11. Health Checks

Health registration is optional.

Health checks should be:

- inexpensive
- deterministic
- honest

Do not perform expensive external operations during health checks.

---

# 12. Dependencies

Dependencies are documentation of requirements.

If a Module requires another capability, verify it explicitly before startup.

---

# 13. Best Practices

- Keep ModuleDriver small.
- Keep business logic in ToolDriver or ProviderDriver.
- Use dependency injection.
- Register and unregister symmetrically.
- Never instantiate Core managers.
- Keep Modules independent.
- Make external I/O testable.

---

# 14. Common Mistakes

- Forgetting cleanup during stop().
- Swallowing startup exceptions.
- Registering resources in the wrong order.
- Direct Module-to-Module communication.
- Heavy health checks.
- Assuming dependency ordering.

---

# 15. Testing

Every Module should verify:

- registration
- loading
- unloading
- cleanup
- capability registration
- tool registration
- optional health checks
- end-to-end execution

Use fake implementations for external services.

---

# 16. Packaging

A Module is a normal Python package under:

```text
parika/modules/<module_id>/
```

Register Modules during application bootstrap.

---

# 17. Reference Implementation

The Web Search Module is the canonical implementation and should be used as the reference for new Modules.

For a Module that registers **several** Capabilities/Tools (rather
than exactly one), see the Filesystem Module
(`parika/modules/filesystem/driver.py`): it iterates
`parika.tools.filesystem.manifest.FILESYSTEM_OPERATIONS` in `start()`/
`stop()` to register/unregister every Capability and Tool
symmetrically, keeping the loop itself the only thing that scales with
the number of Capabilities. The Weather, Currency, and News Modules
follow the same shape with a small, explicit list instead of a data
table, since each has only 2-3 Capabilities. See `Tool_Guide.md` §21
for why a Tool implementing several Capabilities must still be
registered as several separate Tool instances.

**Deviations from the original Tools Expansion plan:** the `news`
Module's `feedparser` dependency shipped as a required base dependency
rather than the optional extra originally proposed (see `Tool_Guide.md`
§21's note); a proposed internal split of `parika/tools/runtime_info/`
and optional `watchdog`/`trafilatura` extras for filesystem-watching and
richer page-content extraction were never implemented - `filesystem.watch`
uses simple polling and the Web Search Tool's page fetcher uses only the
standard library, matching the project's Standard-Library-First policy.

---

# 18. Developer Intelligence Platform Modules

Three Modules, registered/loaded in this exact order in
`parika/interfaces/runtime.py`'s `_register_modules()` (dependency
order: each constructs collaborators the next one receives), deliver
Coding Tool understanding, Workspace/Repository Understanding +
Project Indexing, and the Coding Agent. None of the three introduces a
new Core component; each follows an already-established pattern from
earlier sections of this guide.

## 18.1 `coding` -- registers the Coding Tool

`parika/modules/coding/driver.py`'s `CodingModuleDriver` follows the
"iterate a data table to register several Capabilities/Tools" shape
§17 already describes for the Filesystem Module
(`CODING_OPERATIONS`, see `Tool_Guide.md` §24). It owns
`coding_index.sqlite3`'s lifecycle (`initialize()` in `start()`,
`shutdown()` in `stop()`) and exposes its `CodingIndexStorage`/
`LanguageAnalyzerRegistry` as read-only properties (`.storage`,
`.registry`) so `repository_intelligence` (§18.2) can reuse the exact
same instances -- a plain Python object reference passed at
composition-root wiring time in `runtime.py`, not a Module-to-Module
dependency, since the Coding Tool package itself has no Module
identity or driver.

## 18.2 `repository_intelligence` -- Workspace/Repository Understanding + Project Indexing

`parika/modules/repository_intelligence/driver.py`'s
`RepositoryIntelligenceModuleDriver` registers one new `KnowledgeEngine`
implementation, `RepositoryKnowledgeEngine`, with the existing,
unmodified `KnowledgeManager` via its public `register_engine()` API --
the same pattern the Knowledge Indexing Module already uses for
`DocumentKnowledgeEngine`/`CodeKnowledgeEngine`. It supports the
already-existing `KnowledgeSourceKind.REPOSITORY`/`.WORKSPACE` kinds;
no change to `KnowledgeManager`, `KnowledgeSource`,
`KnowledgeSourceKind`, or `KnowledgeStorage` was required.

**Registration order matters here.** `CodeKnowledgeEngine` (Knowledge
Indexing Module) and `RepositoryKnowledgeEngine` both declare
`supports()=True` for `REPOSITORY`/`WORKSPACE`, and
`KnowledgeEngineRegistry.resolve()` is a first-match registry (frozen,
unmodified Core behavior -- it has no "most specific wins" rule). To
make `RepositoryKnowledgeEngine` the one actually resolved,
`runtime.py` loads `coding` and `repository_intelligence` **before**
`knowledge_indexing`. `CodeKnowledgeEngine` remains registered,
unmodified, and its own unit tests (constructed in isolation, with no
competing engine) are unaffected -- this ordering only decides which
engine wins when both are registered together in the same runtime.
**If you ever add another `KnowledgeEngine` supporting an existing
source kind, check `runtime.py`'s load order for this exact
conflict.**

Beyond engine registration, this driver exposes `index_workspace(location)`
(idempotent `KnowledgeSource` registration + content-hash-gated
`index_incremental()`) and a `git_reader` (`GitReader`, exactly three
fixed, read-only `git` subcommands run through the existing Shell
Tool's `shell.execute` -- Git is never used to modify a repository).

## 18.3 `coding_agent` -- the Coding Agent

`parika/modules/coding_agent/module_driver.py`'s
`CodingAgentModuleDriver` registers `coding.execute_task`
(`category=CapabilityCategory.TOOL` -- it must be `TOOL`, not
`AUTOMATION` or any other category, because Planner only routes a Goal
to `ToolManager` when `resolution.definition.category is
CapabilityCategory.TOOL`; every other category is assumed to require a
Provider model) with its `tool.coding_execute_task` Tool, and
`coding.plan_change` (`category=CapabilityCategory.LLM`, satisfied by a
Provider model exactly like `chat.respond`, never a Tool).

`CodingAgentToolDriver` (the `ToolDriver` for `coding.execute_task`) is
a **pure orchestrator**: it builds a `CodingTaskDescriptor`, asks an
internal `CodingAgentRegistry` for the matching `CodingAgent`
implementation, and delegates. It never implements filesystem logic,
shell execution, or indexing itself -- `StandardCodingAgent` (the one
required, default implementation) reaches every one of those only by
constructing `Goal`/`BrainRequest` objects and calling
`Brain.handle()`/`Brain.assemble_context()`, both existing, unmodified
Core APIs.

**Internal, pluggable multi-agent extensibility** (not part of the
public Capability contract): `CodingAgentRegistry` holds a tuple of
`CodingAgent` implementations; `.select(task)` picks the first whose
`supports(task)` returns `True` (an explicit `task.requested_agent_id`
-- from the optional `ToolRequest.arguments["agent"]` -- always wins
first). Adding a "Fast"/"Security Review"/"Documentation" agent later
is: implement the `CodingAgent` Protocol (`id`, `supports()`,
`execute()`), pass it via `CodingAgentModuleDriver`'s `extra_agents`
constructor parameter. Zero change to `coding.execute_task`'s public
shape, `ToolManager`, `Planner`, or `Brain`. `supports()` must stay
cheap and deterministic -- the same "inexpensive, deterministic,
honest" discipline §11 already requires of health checks; a future
agent needing real reasoning to decide applicability should decide
*inside* its own `execute()`, not inside `supports()`.

**Reentrancy guard:** a plan step naming `coding.execute_task` again
carries `metadata={"coding_agent_depth": task.depth + 1}` on its Goal;
`CodingAgentToolDriver.execute()` reads
`request.metadata["coding_agent_depth"]` back into the new
`CodingTaskDescriptor.depth`, and the plan-validation gate
(`parika/modules/coding_agent/plan.py::validate_plan()`) rejects any
such step once `depth + 1 > max_depth` -- deterministic, not trusted to
the model.

## 18.4 `ocr` -- the OCR Module

`parika/modules/ocr/module_driver.py`'s `OcrModuleDriver` registers
`ocr.extract_text` (`category=CapabilityCategory.TOOL` -- same reason
as `coding.execute_task` in §18.3: Planner only routes a Goal to
`ToolManager` when `resolution.definition.category is
CapabilityCategory.TOOL`, and Automatic Capability Discovery
(`ai_context/capability_context.py`) only ever advertises TOOL-category
Capabilities to the model) with its `tool.ocr_extract_text` Tool, and
`ocr.provider_extract_text` (`category=CapabilityCategory.OCR`,
satisfied by a Provider model such as `glm-ocr`, never a Tool, and
never advertised directly to the model) -- the exact same
two-Capability shape §18.3 already establishes for
`coding.execute_task`/`coding.plan_change`.

`OcrToolDriver` (the `ToolDriver` for `ocr.extract_text`) is a **pure
orchestrator**, following `CodingAgentToolDriver`/`StandardCodingAgent`
exactly: it never reads the filesystem or talks to a Provider itself.
It reaches both existing Capabilities only by constructing
`Goal`/`BrainRequest` objects and calling `Brain.handle()`:

1. `Goal(capability_id="filesystem.read", inputs={"path": ..., "binary": True})`
   obtains the image's bytes, base64-encoded, through the existing,
   unmodified Filesystem Capability -- the same security/permission
   path (`WorkspacePermissionManager`, `PathSecurity`) every other
   caller already uses. Reads are unconditionally allowed by the
   Permission System already, exactly as for any other `filesystem.read`
   call.
2. `Goal(capability_id="ocr.provider_extract_text", provider_request_builder=...)`
   recognizes the image's text through the unmodified Model Selection
   Framework: `Planner._select_provider_model()` derives
   `CapabilityCategory.OCR -> ModelCapability.VISION`
   (`CATEGORY_TO_MODEL_CAPABILITY`, `planner.py`) and
   `TaskCategory.OCR` (`_CATEGORY_TASK_DEFAULTS`,
   `task_classification.py`, both already existing), so the existing
   `glm-ocr`-style `required_specializations={"ocr"}` filtering
   (`filtering.py`, already covered by
   `tests/providers/ollama/test_glm_ocr_regression.py`) selects an
   OCR-capable model, exactly as it already does when driven directly.
   `provider_request_builder` -- the exact mechanism
   `StandardCodingAgent._submit_decomposition_goal()` already uses for
   `coding.plan_change` -- supplies the base64 image data as
   `OllamaMessage(images=(...))`, Ollama's own provider-specific
   wire-serialization field (`parika/providers/ollama/messages.py`;
   see §4.4's Tool Affordance Contract and
   `docs/architecture/PARIKA_Decision_Flow.md` section 4.4 for why the
   *caller* -- never Planner -- builds this concrete, provider-specific
   payload). No `base64`/`images[]`/Ollama-specific concept appears
   anywhere outside `parika/providers/ollama/`; the OCR Module only
   ever passes an opaque, already-encoded string through.

Because both steps are ordinary nested `Goal`s resolved by the
unmodified Planner/Brain/Model Selection Framework, `ocr.extract_text`
never bypasses `WorkspacePermissionManager`, `PathSecurity`, or the
Filesystem Module, and `ocr.provider_extract_text` never bypasses
Model Selection's filtering/scoring pipeline -- exactly the same
guarantee §18.3 already documents for the Coding Agent.

### 18.4.1 OCR Extension: Preprocessing, PDF Support, and Structured Extraction

The OCR Module was later extended with seven further TOOL
Capabilities, deterministic image/PDF/language algorithms, and two
additive inputs on `ocr.extract_text` itself -- purely additive, zero
changes to Planner, Model Selection, AI Context Engineering, or
`runtime.py`'s existing registration/load calls (both already
constructed `OcrModuleDriver`/`create_ocr_module()` before this
extension existed).

**Shared primitives (`engine.py`).** `OcrToolDriver`'s original two
Brain-mediated steps -- `filesystem.read`, then
`ocr.provider_extract_text` -- were extracted, behavior-preserving,
into `read_image_base64()`/
`recognize_text()`, so every driver below reuses exactly one
implementation rather than repeating the same `Goal`/`BrainRequest`
wiring per Tool.

**Deterministic algorithms, never a model call:**

- `preprocessing.py` (requires the optional `ocr` dependency group --
  Pillow, numpy; see below): EXIF-based rotation correction,
  projection-profile skew estimation/correction, variance-of-Laplacian
  blur detection, a composite quality score, contrast/denoise/upscale,
  and Otsu-threshold-based table-region (ruled-line) detection.
  `detect_orientation()`'s own docstring documents its one honest
  limitation: row-projection variance cannot distinguish upright from
  upside-down (0 vs 180 degrees) for any image, since vertical
  reversal does not change variance -- portrait-vs-landscape (0/180 vs
  90/270) is reliably distinguished; the 0-vs-180 tie deterministically
  prefers "no rotation".
- `pdf_support.py` (requires `pypdfium2`): per PDF page, attempts
  zero-cost text-layer extraction first; only renders a page to an
  `Image` -- for the same deterministic-then-Provider pipeline every
  other image already uses -- when its text layer is shorter than
  `[ocr].pdf_min_text_layer_chars`, avoiding a model call entirely for
  born-digital PDF pages.
- `language.py` (requires `langdetect`, seeded for determinism):
  statistical language detection over already-recognized text.
- `document_types.py`: the `document_type` -> instruction/expected-
  fields data table (`DOCUMENT_TYPE_TEMPLATES`), retained for its own
  `parse_structured_response()`'s best-effort, never-raising JSON
  extraction from a model's raw text response (handles a bare JSON
  body, a Markdown ```json fence, or JSON embedded in prose; reports
  `parsed=False` with the raw text preserved otherwise), reused by
  `ocr.extract_table`/`ocr.extract_form`.

Every deterministic feature above is auto-detected at runtime
(`config.py`'s `pillow_dependency_available()`/
`imaging_dependency_available()`/`pdf_dependency_available()`/
`language_detection_dependency_available()`, each via
`importlib.util.find_spec()`) and gracefully unavailable -- raising
`OcrDependencyUnavailableError`, never crashing at import time --
exactly the same pattern §18.1's `coding.tree_sitter_enabled` already
establishes for its own optional dependency. `ocr.extract_text`/
`ocr.provider_extract_text` never depend on any of it.

**`ocr.extract_text` itself** gained two additive inputs, each falling
back to the original, unmodified default when omitted: `region`
(crops before recognition -- fewer pixels sent to the Provider model
for region-specific OCR) and `language` (folded deterministically into
the instruction text). It is also transparently PDF-aware: a PDF is
sniffed by content (`pdf_support.is_pdf()`), never by trusting a
`.pdf` extension, and handled page by page, with page numbering
preserved in the response's `pages` list -- previously undefined/
unusable behavior (a raw PDF byte blob is not a valid image), so no
existing caller or test is affected.

**Six further TOOL Capabilities**, registered from the same
`OcrModuleDriver`, each reusing the *existing*, unmodified
`ocr.provider_extract_text` Provider Capability wherever a model call
is genuinely needed -- never a new Provider Capability per Tool, since
table/form extraction shares the exact same
`required_specializations={"ocr"}` selection criterion
`ocr.extract_text` already uses:

| TOOL Capability | Driver | Model call? |
| --- | --- | --- |
| `ocr.detect_orientation` | `analysis_driver.OcrOrientationToolDriver` | Never |
| `ocr.detect_quality` | `analysis_driver.OcrQualityToolDriver` | Never |
| `ocr.detect_language` | `text_tools_driver.OcrLanguageToolDriver` | Only if no `text` already given |
| `ocr.extract_layout` | `text_tools_driver.OcrLayoutToolDriver` | Only if no `text` already given |
| `ocr.extract_table` | `structured_driver.OcrTableToolDriver` | Always (`ocr.provider_extract_text`) |
| `ocr.extract_form` | `structured_driver.OcrFormToolDriver` | Always (`ocr.provider_extract_text`) |

`ocr.detect_language`/`ocr.extract_layout` accept *either* an
already-known `text` argument (zero Brain calls at all -- the common
case, when the calling model already ran `ocr.extract_text` earlier in
the same turn) or a `path` fallback (one `ocr.provider_extract_text`
call, exactly like `ocr.extract_text`'s own cost) -- each Tool
Affordance Contract's `use_when`/`avoid_when` text nudges the calling
model toward the zero-cost `text` path using the existing, generic
mechanism `ai_context/tool_context.py` already reads every
Capability's contract through; no new mechanism was added.
`ocr.extract_table`'s table-*region* detection is always deterministic
(`table_detection.detect_table_regions()`); only table *content*
extraction into rows/columns is delegated to a model, since that is
genuinely the "semantic reasoning actually required" case -- turning
pixels into structured field/row semantics has no dedicated table-
structure-recognition model available.

`document.extract_text` (formerly a temporary implementation detail of
this Module, registered here as `structured_driver.OcrDocumentToolDriver`)
has moved to the first-class Document Module -- see §18.6.

See `docs/development/Capability_Guide.md` §17 for the full `ocr.*`
namespace table and `[ocr]` in `config/defaults.toml` for every
tunable (deskew angle, blur/quality thresholds, PDF render DPI/text-
layer threshold) -- all freely editable with no code change, following
the same convention every other Module's configuration section
already uses.

## 18.5 `vision` -- the Vision Module

`parika/modules/vision/module_driver.py`'s `VisionModuleDriver`
registers the general-purpose image-understanding Capability family --
the reusable foundation for every current and future image
understanding task -- by repeating §18.4's exact `ocr.extract_text`/
`ocr.provider_extract_text` two-Capability shape once per
`VisionToolSpec` in its own `_VISION_TOOL_SPECS` table, rather than
introducing any new execution architecture:

| Advertised TOOL Capability (`category=CapabilityCategory.TOOL`) | Internal Provider Capability (`category=CapabilityCategory.VISION`) | Purpose |
| --- | --- | --- |
| `vision.describe_image` | `vision.provider_describe_image` | General image description. |
| `vision.answer_question` | `vision.provider_answer_question` | Visual Question Answering (requires a `question` argument instead of an optional `instruction` one). |
| `vision.detect_objects` | `vision.provider_detect_objects` | Object detection/counting. |
| `vision.analyze_scene` | `vision.provider_analyze_scene` | Scene/environment analysis. |
| `vision.analyze_ui` | `vision.provider_analyze_ui` | Application UI/webpage screenshot analysis. |
| `vision.analyze_chart` | `vision.provider_analyze_chart` | Chart/graph/plot analysis. |
| `vision.analyze_diagram` | `vision.provider_analyze_diagram` | Architecture diagram/flowchart/network diagram analysis. |

Every TOOL Capability above is backed by its own `tool.vision_*` Tool
and shares one `VisionToolDriver` class (`parika/modules/vision/
driver.py`) -- a **pure orchestrator**, following `OcrToolDriver`
exactly: it never reads the filesystem or talks to a Provider itself.
Each instance is constructed bound to its own provider capability id
and default instruction (or, for `vision.answer_question` only, a
required `question` argument used verbatim as the instruction), and
reaches both existing Capabilities only by constructing
`Goal`/`BrainRequest` objects and calling `Brain.handle()`:

1. `Goal(capability_id="filesystem.read", inputs={"path": ..., "binary": True})`
   obtains the image's bytes, base64-encoded, through the existing,
   unmodified Filesystem Capability -- identical to §18.4's own first
   step.
2. `Goal(capability_id=<its own vision.* provider capability>, provider_request_builder=...)`
   analyzes the image through the unmodified Model Selection
   Framework: `Planner._select_provider_model()` derives
   `CapabilityCategory.VISION -> ModelCapability.VISION`
   (`CATEGORY_TO_MODEL_CAPABILITY`, `planner.py`, already existing --
   unchanged for Vision) and `TaskCategory.VISION_UNDERSTANDING`
   (`_CATEGORY_TASK_DEFAULTS`, `task_classification.py`, already
   existing), so the existing `required_specializations=
   {"vision_understanding"}` filtering (`filtering.py`) selects a
   Vision-capable model such as `minicpm-v4.5`. Exactly like `glm-ocr`
   needed a Local Curated Override (`parika/core/semantics/
   model_knowledge.py`, formerly `overrides.py` -- evolved into
   PARIKA Model Knowledge as part of the AI-Assisted Model Selection
   Refinement milestone; see `Model_Selection_Framework.md` §13.4) to
   be recognized as `"ocr"`-specialized despite Ollama's raw
   `/api/show` metadata only proving it accepts image input,
   `minicpm-v4.5` needed the same override extended with
   `"vision_understanding"` -- a data-only addition, not a change to
   the override mechanism itself. `provider_request_builder` supplies
   the base64 image data as `OllamaMessage(images=(...))`, identical
   to §18.4's own second step.

No `CapabilityCategory` or `CATEGORY_TO_MODEL_CAPABILITY` change was
needed for Vision: `CapabilityCategory.VISION` and its
`ModelCapability.VISION`/`TaskCategory.VISION_UNDERSTANDING` mappings
already existed (added when the Model Selection Framework's Task
Classification layer was introduced), and Automatic Capability
Discovery/Tool Affordance rendering (`ai_context/tool_context.py`,
`ai_context/capability_context.py`) already handle any newly
registered TOOL Capability generically. Registering the Vision Module
was therefore purely additive: seven new `CapabilityDefinition`/`Tool`
pairs, one new Module, one new `SpecializationOverride` entry -- zero
changes to Planner, Model Selection, or AI Context Engineering.

Because every step is an ordinary nested `Goal` resolved by the
unmodified Planner/Brain/Model Selection Framework, no `vision.*` TOOL
Capability ever bypasses `WorkspacePermissionManager`, `PathSecurity`,
or the Filesystem Module, and no `vision.*` Provider Capability ever
bypasses Model Selection's filtering/scoring pipeline -- exactly the
same guarantee §18.3 and §18.4 already document.

### 18.5.1 Vision Extension: Deterministic-First Comparison, Detection, Quality, Collection, and Editing Capabilities

Twenty-four further `vision.*` Capabilities extend the Module above
with comparison, detection, quality/anomaly analysis, multi-image
collection, and editing tasks -- mirroring §18.4.1's own "extend, do
not redesign" precedent exactly. Two (`vision.detect_logos`,
`vision.reason_about_image`) are purely Provider-backed and simply
join `_VISION_TOOL_SPECS` as two more `VisionToolSpec` rows (zero new
driver code -- no classical algorithm can identify a brand or reason
open-endedly about an image). The remaining twenty-two are declared in
a second, parallel table, `_VISION_EXTENDED_TOOL_SPECS`
(`_VisionExtendedToolSpec`, `extended_tool_specs.py` -- split out of
`module_driver.py`, together with the `build_extended_tool_drivers()`
factory in `extended_tool_drivers.py`, purely to keep `module_driver.py`
within the project's File Size Guidelines), each with its own
dedicated `ToolDriver` and an *optional* `provider_capability_id` --
optional because, unlike every Capability above, most of these can
answer their own question deterministically:

- **Always deterministic, opt-in Provider narration**
  (`driver_compare.py`/`driver_quality.py`/`driver_detection.py`/
  parts of `driver_collection.py`): `vision.compare_images`,
  `vision.detect_differences`, `vision.detect_faces`,
  `vision.detect_qr_codes`, `vision.detect_barcodes`,
  `vision.analyze_image_quality`, `vision.detect_blur`,
  `vision.detect_rotation`, `vision.detect_anomalies`,
  `vision.find_similar_images`, `vision.find_duplicates`. Each
  ToolDriver *always* runs its own classical algorithm
  (`hashing.py`/`quality.py`/`detectors.py` -- perceptual hashing,
  variance-of-Laplacian blur, row-projection-profile rotation,
  Haar-cascade face detection, ZBar QR/barcode decoding, Otsu-
  threshold blob counting, grid z-score anomaly scanning) and returns
  it directly; it only additionally issues a
  `Goal(capability_id=<its own vision.provider_*>, ...)` -- exactly
  §18.5's own step 2, with `images_base64` extended to more than one
  image where relevant (`engine.analyze_with_provider()`) -- when the
  caller supplies a non-empty `instruction` (or, for
  `find_similar_images`/`find_duplicates`, sets
  `verify_with_model=True`). This is the "prefer deterministic
  computer vision algorithms before invoking a Vision Language Model"
  requirement, applied literally: the model call is additive and
  strictly opt-in, never load-bearing for the primary result.
- **Deterministic-first with a genuine semantic fallback**
  (`driver_counting.py`): `vision.count_objects` (Otsu/connected-
  component blob count, `detectors.count_blobs()`) and
  `vision.classify_image` (edge-density/color-cardinality heuristic,
  `detectors.classify_image_heuristic()`) both fall back to their own
  Provider Capability specifically when the deterministic path cannot
  answer the actual question asked (a *named* object type, or
  open-set candidate `labels`) -- not merely on request.
- **Genuinely semantic** (`driver_collection.py`):
  `vision.search_images` has no deterministic path at all (finding
  images that show something described in words requires recognizing
  image content); it issues one bounded, per-candidate Provider Goal
  (capped by `max_candidates`/`[vision].max_search_candidates`),
  the one Capability in this Module where the model call is the
  primary mechanism, not an addable narration.
- **Purely deterministic editing** (`driver_editing.py`):
  `vision.crop_image`, `vision.resize_image`, `vision.rotate_image`,
  `vision.flip_image`, `vision.convert_format`, `vision.compress_image`
  register *no* Provider Capability at all -- pure Pillow transforms
  (`editing.py`), writing the result through a new
  `Goal(capability_id="filesystem.write", inputs={"path": ...,
  "binary": True, "content_base64": ...})` (`engine.write_image_base64()`),
  the direct write-side counterpart to §18.5's own
  `filesystem.read` step.
- **Deterministic editing with opt-in Provider notes**
  (`driver_editing.py`): `vision.enhance_image` (auto-contrast +
  unsharp mask, `editing.enhance()`) and `vision.remove_background`
  (classical GrabCut segmentation, `segmentation.remove_background()`,
  OpenCV's decades-old graph-cut algorithm, not a trained model) both
  apply their deterministic pipeline unconditionally and only add a
  short Provider-sourced `notes` string -- never used to alter the
  deterministic pixels themselves -- when the caller supplies an
  `instruction`.

Face detection (`detectors.detect_faces()`) and background removal
(`segmentation.remove_background()`) require the optional
`opencv-python-headless` dependency; QR/barcode decoding
(`detectors.detect_qr_codes()`/`detect_barcodes()`) require the
optional `pyzbar` dependency (plus the system ZBar shared library) --
both part of the new `vision` extra (`pyproject.toml`). Every other
new Capability needs only Pillow/numpy, already base dependencies.
Exactly like `ocr.provider_extract_text` always working regardless of
the `ocr` extra, every one of this Module's Provider-backed
Capabilities always works with zero new dependency; only the
`opencv`/`pyzbar`-backed deterministic paths degrade gracefully (a
clear `VisionDependencyUnavailableError`, never a crash) when the
`vision` extra is not installed (`parika/modules/vision/config.py`,
mirroring `ocr/config.py`'s `require_imaging()` pattern exactly).

No `CapabilityCategory`, `CATEGORY_TO_MODEL_CAPABILITY`, Planner, or
Model Selection change was needed for any of this: every new Provider
Capability reuses the exact same `CapabilityCategory.VISION ->
ModelCapability.VISION -> TaskCategory.VISION_UNDERSTANDING` routing
§18.5 already established, and every new TOOL Capability is
discovered/advertised generically by the unmodified Automatic
Capability Discovery/Tool Affordance machinery. This extension is
therefore purely additive: twenty-four new `CapabilityDefinition`/
`Tool` pairs (eighteen with a companion Provider Capability, six
without), six new deterministic algorithm modules (`hashing.py`,
`quality.py`, `detectors.py`, `segmentation.py`, `editing.py`,
`regions.py`), one shared orchestration module (`engine.py`), and one
new optional dependency extra -- zero changes to Planner, Model
Selection, AI Context Engineering, or any other Module (OCR, Document,
Video, Generation included).

## 18.6 `document` -- the Document Module

`parika/modules/document/module_driver.py`'s `DocumentModuleDriver` is
PARIKA's single entry point for document processing: it orchestrates
native, deterministic parsing, delegates to the existing, unmodified
OCR Module for scanned/image-only PDFs, and delegates semantic
reasoning to one shared, internal Provider Capability -- introducing
no new execution architecture beyond what §18.4/§18.5 already
established. Thirty-four TOOL Capabilities in total, grouped by shape:

**Reading** (`driver_reading.DocumentReadingToolDriver`, deterministic,
never a model call): `document.extract_text` (auto-detects the format
from the path) plus ten format-fixed `document.read_*` Capabilities
(`read_pdf`, `read_docx`, `read_pptx`, `read_xlsx`, `read_markdown`,
`read_html`, `read_txt`, `read_csv`, `read_json`, `read_xml`). Every
format maps into one provider-independent `UnifiedDocument`
(`document_model.py`) via `pipeline.parse_document()`:

1. `pdf`: delegated entirely to the existing, unmodified
   `ocr.extract_text` Capability (`engine.ocr_extract_text()`, a
   nested `Goal` exactly like §18.4/§18.5's own `filesystem.read`
   step) -- which already implements "native text layer first,
   per-page OCR fallback only for scanned/image-only pages"
   (`ocr/pdf_support.py`). This Module never performs OCR itself,
   never renders a page, and never calls a Vision/OCR Provider model
   directly.
2. Text-native formats (markdown/html/txt/csv/json/xml): read via
   `Goal(capability_id="filesystem.read", inputs={"binary": False})`,
   then parsed deterministically by stdlib-only code
   (`readers.py`) -- HTML additionally uses the optional
   `beautifulsoup4` dependency when installed, falling back to a
   regex-based stdlib parser otherwise (never a crash).
3. Office Open XML formats (docx/pptx/xlsx): read via
   `Goal(capability_id="filesystem.read", inputs={"binary": True})`,
   then parsed by the optional `python-docx`/`python-pptx`/`openpyxl`
   dependencies (`pyproject.toml`'s `document` extra;
   `config.py`'s `require_docx()`/`require_pptx()`/`require_xlsx()`
   raise a typed `DocumentDependencyUnavailableError`, never crashing,
   when one is missing).

**Extraction** (`driver_extraction.DocumentExtractionToolDriver`,
deterministic, never a model call, per the spec's own "never use an
LLM for ... links, headings, page count, images, tables, document
structure" guidance): `document.extract_metadata`,
`document.extract_images`, `document.extract_tables`,
`document.extract_links`, `document.extract_headings`,
`document.extract_sections`, `document.extract_references`,
`document.extract_attachments` -- each obtains the same
`UnifiedDocument` Reading obtains (`pipeline.parse_document()`, never a
second parsing path) and returns only the requested facet.

**Analysis, semantic** (`driver_analysis.DocumentAnalysisToolDriver`,
one shared internal Provider Capability,
`document.provider_analyze_content`, `category=CapabilityCategory.LLM`
-- satisfied by whichever general-purpose text-generation Provider
model the Model Selection Framework selects, never a hardcoded model
name, mirroring `ocr.provider_extract_text`'s/`vision.provider_*`'s
own single-shared-capability precedent exactly):
`document.summarize`, `document.answer_question`,
`document.compare_documents`, `document.classify`,
`document.detect_document_type`, `document.extract_entities`,
`document.extract_action_items`, `document.extract_timeline`,
`document.translate`. The document's own text (obtained via the same
Document Pipeline) is sent as a plain-text `OllamaMessage` -- never an
image -- via `engine.analyze_content()`.

**Analysis, deterministic** (`driver_analysis_deterministic
.DocumentDeterministicAnalysisToolDriver`, `text_analysis.py`, never a
model call -- "never invoke an LLM if deterministic extraction is
sufficient"): `document.search` (substring/regex), `document
.detect_language` (the same base `langdetect` dependency
`ocr.detect_language` uses, via its own independent wrapper --
language detection over plain text is a generic NLP utility, not OCR
logic), `document.extract_keywords` (term-frequency heuristic),
`document.extract_dates`/`document.extract_contacts` (regex),
`document.detect_duplicates` (content-hash + Jaccard word-set
similarity).

Because every nested step is an ordinary `Goal` resolved by the
unmodified Planner/Brain/Model Selection Framework (including the one
call into the OCR Module), no `document.*` Capability ever bypasses
`WorkspacePermissionManager`, `PathSecurity`, the Filesystem Module, or
Model Selection's filtering/scoring pipeline -- exactly the same
guarantee §18.3/§18.4/§18.5 already document. See
`docs/development/Capability_Guide.md` for the full `document.*`
namespace table and `[document]` in `config/defaults.toml` for every
tunable.

## 18.7 `video` -- the Video Module

`parika/modules/video/module_driver.py`'s `VideoModuleDriver` builds
video understanding on top of the existing, unmodified OCR, Vision,
and Document Modules rather than duplicating any of their
implementations -- introducing no new execution architecture beyond
what §18.4-§18.6 already established. Thirty TOOL Capabilities in
total, grouped by shape:

**I/O** (`driver_io.py`, deterministic, never a model call):
`video.read_video`, `video.extract_metadata`, `video.extract_frames`,
`video.extract_keyframes`, `video.extract_thumbnails`. Frame decoding
is `cv2.VideoCapture`-based (`frame_io.py`), the one place in this
Module allowed to open a real filesystem path directly with a
third-party decoder, because video demuxing genuinely requires a
real, seekable file handle -- there is no in-memory-buffer input for
compressed containers. Every path is still validated first through
the existing, unmodified `filesystem.info` Capability
(`engine.resolve_video_path()`, permission-checked, existence-
checked) before `frame_io.py` ever touches it. `video.extract_metadata`
additionally attempts a best-effort `ffprobe` enhancement (bitrate,
accurate codec, audio-stream presence) exclusively through the
existing, unmodified Shell Tool's `tool.shell_execute` Capability,
mirroring `repository_intelligence/repository/git_reader.py`'s own
fixed, read-only, argv-form external-command precedent
(`metadata_probe.probe_with_ffprobe()`); silently skipped (never a
crash) when `ffprobe`/the Shell Tool are unavailable.

**Video understanding** (`driver_understanding.py`): `video
.describe_video`, `video.summarize_video`, `video.answer_question`,
`video.classify_video`. Each adaptively samples a bounded,
representative set of frames (`sampling.py`) and invokes exactly one
multimodal Provider Goal carrying every sampled frame in one Ollama
message (never one call per frame) against this Module's own internal
Provider Capability (`video.provider_describe_video`, `video
.provider_summarize_video`, `video.provider_answer_question`, `video
.provider_classify_video`). `video.classify_video` computes a
deterministic coarse category (scene-change/motion statistics) first,
escalating to its Provider Capability only when the caller supplies
open-set `candidate_labels`.

**Timeline** (`driver_timeline.py`, temporal understanding -- the
primary distinction from Vision): `video.generate_timeline`, `video
.detect_scene_changes`, `video.detect_shots`, `video.segment_video`
(all built on `scene_detection.py`'s deterministic frame-comparison
shot-boundary detector, never a model call), and `video
.detect_key_moments` (deterministic candidate ranking, with an
opt-in explanation via its own `video.provider_detect_key_moments`).

**Objects and motion** (`driver_objects.py`, `driver_motion.py`):
`video.detect_objects`/`video.count_objects`/`video.track_objects`
reuse Vision's own `vision.provider_detect_objects` Provider
Capability directly (`engine.detect_objects_in_frame()`) rather than a
second detection stack; `video.count_objects`'s default path and
`video.track_objects`'s fallback (this environment's
`opencv-python-headless` ships without the legacy contrib tracking
API) stay deterministic. `video.detect_motion`/`video.compare_frames`
are 100% deterministic frame-differencing (`motion.py`/`hashing.py`).

**Events, text, and documents** (`driver_events.py`, `driver_text.py`,
`driver_documents.py`): `video.detect_events` (deterministic
candidates: scene changes, motion spikes, black-frame transitions);
`video.detect_actions` (genuinely requires a model, via its own
`video.provider_detect_actions`, with a `confidence` derived from the
underlying motion level); `video.extract_text` reuses OCR's own
`ocr.provider_extract_text` Capability directly
(`engine.extract_text_from_frame()`), deduplicating near-identical
frames/repeated text; `video.detect_documents`/`video.detect_slides`/
`video.extract_tables` reuse the same OCR Provider Capability for
text-density/table-heuristic signals rather than a second OCR or
table-recognition engine.

**Comparison and quality** (`driver_compare_videos.py`,
`driver_quality.py`): `video.compare_videos` (deterministic metadata/
visual-similarity/scene-structure comparison, escalating to Vision's
own `vision.provider_compare_images` only when `include_semantic_diff`
is set) and the fully deterministic `video.detect_blur`, `video
.detect_black_frames`, `video.detect_rotation`, `video
.detect_corruption`.

**Cross-Module reuse mechanism** (`engine.py`): every `video.*` Tool
that needs semantic reasoning on an in-memory decoded frame targets a
*sibling* Module's own Provider Capability directly
(`vision.provider_describe_image`, `vision.provider_detect_objects`,
`vision.provider_compare_images`, `ocr.provider_extract_text`) via a
nested `Goal` through `Brain.handle()` -- exactly the same dynamic,
Goal-based reuse mechanism Document uses for `ocr.extract_text`
(§18.6), just targeting the Provider-level sibling Capability instead
of the Tool-level one, since Vision's/OCR's TOOL Capabilities only
accept a filesystem `path` (they call `filesystem.read` internally)
and writing every sampled video frame to disk merely to read it back
would be wasted I/O. This Module's own six internal Provider
Capabilities (`video.provider_describe_video`, `video
.provider_summarize_video`, `video.provider_answer_question`, `video
.provider_classify_video`, `video.provider_detect_key_moments`,
`video.provider_detect_actions`) are registered with
`category=CapabilityCategory.VISION` rather than a new `VIDEO`
category -- this framework has no `VIDEO` `CapabilityCategory`
member, and reusing `VISION`'s existing `ModelCapability.VISION`
routing mirrors OCR's own precedent of reusing `VISION` for a
different modality (every Provider Capability in this Module is, in
the end, satisfied by sending frame images through
`OllamaMessage.images`).

Deterministic frame decoding requires the optional `video` dependency
group (`opencv-python-headless`, the same dependency the `vision`
extra already installs -- deliberately reused rather than adding a
second video-decoding dependency such as PyAV/moviepy/imageio);
gracefully degrading (`config.py`'s `require_opencv()`, never a crash)
when it is not installed. See `docs/development/Capability_Guide.md`
for the full `video.*` namespace table and `[video]` in
`config/defaults.toml` for every tunable.

---

# Related Documentation

- architecture/PARIKA_Architecture_Specification_v1.0.md
- architecture/Core_Component_Responsibilities.md
- architecture/PARIKA_Core_Component_Blueprint.md
- guides/Testing.md
- guides/Running.md
- Tool_Guide.md
- Capability_Guide.md
- Integration_Checklist.md
