# PARIKA Core Component Responsibilities

**Status:** Definitive quick-reference guide for every Core component.

**Source of truth:** This document summarizes
[`PARIKA_Architecture_Specification_v1.0.md`](PARIKA_Architecture_Specification_v1.0.md)
section 5.2. It does not change, add, or remove any responsibility. If
this document and the Architecture Specification ever disagree, the
Architecture Specification wins.

**Related documents:** [PARIKA_Decision_Flow.md](PARIKA_Decision_Flow.md) for the runtime flow and [PARIKA_Core_Component_Blueprint.md](PARIKA_Core_Component_Blueprint.md) for the component blueprint.

------------------------------------------------------------------------

## 1. Configuration

### Purpose

Acts as the single source of truth for all PARIKA configuration.

### Responsibilities

- Load configuration files.
- Merge configuration layers.
- Validate configuration.
- Provide read-only access to configuration values.
- Locate the PARIKA project root.

### Does NOT

- Store runtime state.
- Modify configuration after loading.
- Manage application services.
- Manage application resources.

> **Why one component, layered, read-only after load:** every other
> component receives configuration through constructor injection
> rather than reading files itself, so a value's precedence
> (`defaults.toml → installation → workspace → environment → runtime.toml`,
> higher layers win) is resolved exactly once, in exactly one place,
> and every consumer sees the same already-merged view -- there is no
> way for two components to disagree about what a config key currently
> means. **Called by:** every other Core component, Module, Tool, and
> Provider that needs a config value (via constructor injection from
> `build_default_runtime()`); the `/config` slash command and the REST
> `/api/v1/config` endpoint (read-only). **Calls:** nothing -- it is a
> leaf component with no dependency on any other Core component.

------------------------------------------------------------------------

## 2. ServiceContainer

### Purpose

Acts as the central registry for shared singleton services used
throughout the PARIKA Core.

### Responsibilities

- Register shared services.
- Retrieve registered services.
- Store singleton service instances.
- Provide centralized access to shared Core services.

### Does NOT

- Perform dependency injection.
- Execute business logic.
- Manage component lifecycle.
- Create service instances.

> **Why this exists despite constructor injection being the primary
> DI mechanism:** `build_default_runtime()` already wires every
> component's real dependencies via its own constructor arguments --
> `ServiceContainer` exists specifically for the read-only,
> after-the-fact introspection that constructor injection cannot serve
> (a slash command or API handler that needs to inspect "what services
> are currently running" without itself being one of `Brain`'s
> constructor-injected dependencies). **Called by:** `build_default_runtime()`
> (registers every constructed singleton) and read-only introspection
> call sites (e.g. the `/status` slash command). **Calls:** nothing.

------------------------------------------------------------------------

## 3. Logger

### Purpose

Provides the centralized logging infrastructure for the entire
application.

### Responsibilities

- Configure the application's logging system.
- Create and configure console and file log handlers.
- Create and provide configured logger instances.
- Maintain the PARIKA logger hierarchy.

### Does NOT

- Decide what should be logged.
- Handle application errors.
- Control application behavior.
- Implement log rotation, filtering, or log storage policies.

> **Why centralized configuration, not per-component `print()`/ad-hoc
> loggers:** the Coding Standards' "never use `print()` inside Core"
> rule (`PARIKA_Core_Coding_Standards.md`) is only enforceable if every
> component gets its logger the same way -- `Logger.get_logger(name)`
> -- so console/file handler configuration, log level, and format are
> controlled from exactly one place (`[logging]` in `config/defaults.toml`)
> regardless of how many components eventually log. **Called by:**
> every other component (via constructor injection, `logger.get_logger(__name__)`).
> **Calls:** the Python standard library `logging` module only.

------------------------------------------------------------------------

## 4. EventBus

### Purpose

Provides synchronous in-process event-driven communication between
PARIKA components.

### Responsibilities

- Register event subscribers.
- Remove event subscriptions.
- Publish events.
- Deliver events to registered subscribers.
- Maintain event subscriptions.

### Does NOT

- Execute workflows.
- Store application data.
- Make business decisions.
- Persist events.
- Maintain event history.
- Perform asynchronous or distributed messaging.

> **Why synchronous and in-process, not asynchronous or distributed:**
> PARIKA is local-first and single-process by design (Architecture
> Spec §2/§3) -- a synchronous, in-process bus means a publisher's
> `publish()` call returns only after every subscriber has run, so
> there is never a "did my subscriber actually see this event yet"
> race to reason about, at the cost of a subscriber's own exception
> never propagating to the publisher (`EventBus` catches and logs it,
> letting every other subscriber still run). **Called by:** effectively
> every Core component, Module, Tool, and Provider that publishes an
> event (see the Channel Catalog below) plus the Console's
> `ConsoleProgressRenderer` and tests (as subscribers). **Calls:**
> nothing -- pure fan-out with no dependency of its own.

### Channel Catalog (illustrative, not exhaustive)

Two families of channels exist, both published by the owning
component itself -- EventBus never originates a channel name or
payload:

- **Domain/lifecycle events** (one typed dataclass per publisher):
  `router.dispatch.*`, `task.*`, `tool.executed`/
  `tool.execution_failed`, `capability.execution.started/completed/
  failed`, `capability.registered/unregistered/enabled/disabled`,
  `provider.*`, `module.*`, `policy.evaluated`, `memory.*`,
  `knowledge.*`, `permission.*`, `health.*`, `lifecycle.*`,
  `update.*`, `workflow.*`, `scheduler.*`.
- **Generic execution-progress events** (Phase 3.5b -- see §5
  "Utilities" below): every publisher's specific channel
  (`f"{source_id}.{stage}"`) plus the fixed generic channel
  (`progress.started/progress/completed/failed`). Current publishers:
  `brain.execution`/`brain.planning`/`brain.execute_goal` (Brain, §29),
  `memory.search` (MemoryManager, §12), `knowledge.search`
  (KnowledgeManager, §13), and any Tool/Module's own `ProgressReporter`
  usage.

`capability.execution.started/completed/failed` (§18 CapabilityExecutor)
additionally carry an optional `task_id` (Phase 3.5b) correlating one
execution to its owning `TaskManager` `Task.id`.

------------------------------------------------------------------------

## 5. Utilities

### Purpose

Provides a shared namespace for reusable utility modules used across
the PARIKA Core.

### Responsibilities

- Organize shared utility modules.
- Provide reusable low-level helper functionality.
- Support multiple Core components through focused utility modules.

### Does NOT

- Contain business logic.
- Own application state.
- Act as a service.
- Contain a Utilities class.
- Introduce utility modules before they are genuinely required.

> **Implementation status:** populated with one module,
> `parika/core/utilities/progress.py` (`ProgressStage`, `ProgressEvent`,
> `ProgressReporter`) -- the generic, ecosystem-wide progress-reporting
> mechanism introduced by the Developer Intelligence Platform (Coding
> Tool, Repository Intelligence, Coding Agent). `ProgressReporter` has
> no lifecycle, no registry, and no business logic beyond formatting an
> immutable `ProgressEvent` and publishing it through the existing,
> unmodified `EventBus` -- it is a plain helper class, never a
> "Utilities class." Every Tool/Module operation that wants to report
> its own real progress constructs (or receives, by dependency
> injection) one `ProgressReporter` bound to its own capability id and
> calls `started()`/`progress()`/`completed()`/`failed()` at the points
> in its own control flow where those transitions genuinely happen.
>
> Each call publishes to two `EventBus` channels: a specific
> `"<source_id>.<stage>"` name (e.g. `"coding.index.progress"`) and a
> fixed, generic `"progress.<stage>"` name -- the latter exists because
> `EventBus.subscribe()` matches by exact string name with no wildcard
> support, so it is what lets any Interface subscribe once, for the
> process's lifetime, and receive progress for every present and future
> Tool/Module with zero code change. Hierarchy (nested progress, e.g.
> "Repository Indexing" containing "Scanning files") is expressed by
> `ProgressReporter.child()`, which returns a new reporter carrying a
> fresh `progress_id`, a `parent_progress_id` pointing at its parent,
> and a `progress_path` (the full root-to-self ancestor chain, needed
> because `EventBus` still never persists events or maintains event
> history). `task_id` (when supplied) correlates to `TaskManager`'s
> `Task.id` but is a deliberately distinct identifier from
> `progress_id`, since one Task's execution can contain an entire tree
> of progress nodes that are never themselves separate Tasks. No
> cancellation or background scheduling is implemented by this module;
> `task_id`/`cancellable` are carried purely so a future increment can
> build on them (`TaskManager.cancel()` and `Scheduler` already exist,
> unmodified, as the components such an increment would use) without
> any redesign of this payload. See
> `parika/tools/coding/driver.py`/`parika/modules/repository_intelligence
> /indexing/repository_knowledge_engine.py`/`parika/modules/coding_agent
> /driver.py` for concrete producers, and
> `tests/core/utilities/test_progress.py` for its test coverage.
>
> **Phase 3.5b extends this mechanism's publishers beyond Tools/
> Modules to three Core components**, using the exact same,
> unmodified `ProgressReporter`/`ProgressEvent` payload and the exact
> same generic-channel convention -- no redesign:
>
> - **Brain** (§29) self-publishes the *root* of execution-progress
>   reporting: one `brain.execution` tree per `Brain.handle()` call
>   (`brain.planning` and `brain.execute_goal` children), via a new
>   optional `event_bus` constructor parameter. Brain is the one
>   component every present and future caller of `handle()` (the
>   Console today; a Scheduler, WorkflowEngine, or Automation caller
>   tomorrow) passes through, so this is the single place that
>   guarantees consistent execution-progress reporting for any caller,
>   without any caller needing to construct its own tree. `Planner`
>   itself is *not* modified: Brain wraps one `plan()` call as a
>   single opaque `brain.planning` node, since planning is fast,
>   synchronous, and has no internally observable sub-stages worth
>   surfacing separately.
> - **MemoryManager** (§12) and **KnowledgeManager** (§13)
>   self-report `memory.search.*`/`knowledge.search.*` around their
>   own `search()` methods, using the `EventBus` each already holds
>   at construction -- as independent, single-level activities, never
>   nested under Brain's or any caller's tree, since they may be
>   invoked from more than one caller.
>
> These three additions are deliberately *not* stitched into one
> combined tree via any new correlation field: `BrainRequest` gained
> no new fields, and `task_id` retains its existing, narrower,
> documented meaning (a real `TaskManager` `Task.id`) rather than
> being repurposed as a whole-request correlator. Console rendering
> (`parika/console/progress_view.py`) relies on temporal ordering
> within one `submit_text()` call, not on any shared identifier,
> to present a coherent sequence of independent activities followed
> by Brain's own nested tree.

------------------------------------------------------------------------

## 6. Security

### Purpose

Provides a shared namespace for low-level security modules used
across the PARIKA Core.

### Responsibilities

- Organize shared security modules.
- Provide reusable low-level security functionality when genuinely
  required.
- Support multiple Core components through focused security modules.

### Does NOT

- Perform authentication.
- Perform authorization.
- Execute security policies.
- Act as a service.
- Contain a Security class.
- Introduce security modules before they are genuinely required.

> **Implementation status:** empty by design. No component currently
> handles credentials, arbitrary file paths, or any of `eval`/`exec`/
> `subprocess`/`pickle`, so there is nothing to secure yet.

------------------------------------------------------------------------

## 7. StateManager

### Purpose

Acts as the single authoritative source of PARIKA's current
operational runtime state.

### Responsibilities

- Maintain lifecycle state.
- Maintain execution state.
- Maintain interaction state.
- Maintain provider state.
- Expose domain-specific operational state APIs.
- Provide a consistent view of PARIKA's current operational state.

### Does NOT

- Store arbitrary runtime data.
- Manage configuration.
- Manage context.
- Manage memory.
- Manage knowledge.
- Manage resources.
- Execute workflows.
- Execute tasks.
- Monitor hardware resources.
- Perform health checks.
- Maintain event history.
- Own lifecycle transition logic.
- Own domain-specific business logic.

> **Interactions and implementation status:** constructed in
> `build_default_runtime()`. Its state-transition setters
> (`set_lifecycle_state()`/`set_execution_state()`/
> `set_interaction_state()`) are called only from inside
> `LifecycleManager` -- and since `LifecycleManager` itself is never
> constructed today (§21), those setters never run in practice, so
> every state getter currently returns its unchanged default. The
> **getters** are, however, genuinely called for read-only
> introspection: the `/status` slash command
> (`parika/interfaces/commands/builtin.py`) and the REST
> `GET /api/v1/status` handler (`parika/api/handlers/status.py`) both
> read `get_lifecycle_state()`/`get_execution_state()`/
> `get_interaction_state()` directly. This is why `StateManager` exists
> as its own component rather than living inside `LifecycleManager`:
> read-only state observation (needed today, by two different
> Interfaces) must not require the state-mutation component
> (`LifecycleManager`, still unimplemented) to exist first.

------------------------------------------------------------------------

## 8. ResourceManager

### Purpose

Provides on-demand information about the current hardware,
operating-system, and filesystem resources available to the running
PARIKA instance -- the single authoritative source of runtime/system
telemetry consumed by the `/status` CLI command, `GET /api/v1/status`,
and (in the future) other Interfaces (Desktop, Voice, ...). No
Interface inspects `psutil`, NVML, or the host OS directly; every one
of them calls `ResourceManager.get_resource_snapshot()` instead.

### Responsibilities

- Provide CPU information (utilization, core counts, load averages
  where the platform exposes `os.getloadavg()`, current frequency).
- Provide memory information (host RAM: total/available/used/free
  bytes and usage percent; swap, where available).
- Provide disk information for the PARIKA workspace filesystem (the
  project root), including usage percent.
- Provide GPU information for every detected device (utilization,
  VRAM, temperature, power draw) via the optional NVIDIA NVML backend
  (the `gpu` extra) -- vendor-neutral in the data model
  (`GPUInfo`/`GPUDeviceInfo`), even though NVML is currently the only
  implemented backend.
- Provide non-GPU thermal sensor information where the host platform
  exposes it (`psutil.sensors_temperatures()`, Linux only).
- Provide basic host network information: hostname resolution,
  interface counts, and aggregate/per-interface byte counters (never
  bandwidth/speed testing).
- Provide host operating-system/architecture/uptime information.
- Provide filesystem accessibility information for configured PARIKA
  directories.
- Produce immutable resource snapshots (`ResourceSnapshot`) combining
  all of the above.
- Compute bounded (`0`-`100`), reasonably-precise usage percentages
  itself wherever a percentage is meaningful, so no Interface/API
  consumer needs to derive one from raw byte counts.
- Degrade every individual metric to `None`/`ResourceStatus.UNKNOWN`
  (never a fabricated zero) when the host platform, driver, or
  optional dependency does not support it -- this must never prevent
  every other metric in the same snapshot from being reported.

### Does NOT

- Decide resource allocation.
- Execute workloads.
- Maintain application state.
- Monitor resources continuously.
- Cache resource information.
- Publish resource events.
- Evaluate health/degradation semantics from the numbers it reports
  (owned by `HealthManager`, kept entirely separate -- see section 22).
- Record its own collection timing/usage as metrics (owned by
  `MetricsManager`, kept entirely separate -- see section 23; no
  coupling between the two components is introduced by runtime
  telemetry).
- Require any GPU-specific dependency to be installed for PARIKA to
  start -- the `gpu` extra (NVML bindings) is optional and always
  gracefully degrades.

> **Why on-demand, not continuous:** a resource-aware `PolicyEngine`
> rule needs a snapshot at the moment it evaluates a Goal, not a
> constantly-refreshed background poll that would run whether or not
> anything ever reads it -- matching the "correctness before
> optimization" principle. This remains true for runtime telemetry:
> `GET /api/v1/status` and the `/status` CLI command each take one
> fresh `get_resource_snapshot()` read per invocation; no scheduler,
> background thread, or EventBus publication was introduced to serve
> them, and a Web Client is expected to poll the API on its own
> schedule (`resources.recommended_client_poll_interval_seconds` in
> `config/defaults.toml`) rather than PARIKA pushing updates to it.
> **Called by:** `Planner.plan()` (`get_resource_snapshot()`, once per
> `plan()` call, never per Goal, to populate the `resource_snapshot` a
> `PolicyRule` can inspect), the `/status` CLI command
> (`parika/interfaces/commands/builtin.py:_status_hardware_lines`),
> and the `GET /api/v1/status` handler
> (`parika/api/handlers/status.py`). No other Core component, Module,
> or Tool calls it today.
>
> **Relationship to HealthManager/MetricsManager:** these three
> components remain fully independent, exactly as before runtime
> telemetry was added. `ResourceManager` reports raw hardware/OS facts
> only -- it has no notion of "healthy"/"degraded" and never asks
> `HealthManager` anything. `HealthManager.overall_status()` continues
> to aggregate registered component health checks only; it does not
> consult CPU/memory/GPU/disk numbers, and `ResourceManager` does not
> register itself with `HealthManager`. `MetricsManager` continues to
> have zero callers; `ResourceManager` does not record its own
> collection duration or any hardware reading through it. `/status`'s
> `overall_health` field and its new `system`/`cpu`/`memory`/`gpu`/
> `temperature`/`storage`/`network` telemetry groups are therefore two
> deliberately independent axes reported side by side, never merged
> into one misleading combined value.
>
> **Privacy:** `system.hostname`/`network.hostname` are populated by
> `ResourceManager` unconditionally (needed by any caller that wants
> it, e.g. the CLI, already running on the user's own machine), but
> `GET /api/v1/status` redacts them to `null` unless an operator opts
> in via `api.expose_hostname` -- the privacy policy is applied at the
> API layer, not inside `ResourceManager` itself, so every other
> caller (CLI, Planner) keeps seeing the real value.

------------------------------------------------------------------------

## 9. CapabilityRegistry

### Purpose

Maintains the authoritative registry of all capabilities available
within PARIKA.

### Responsibilities

- Register capability definitions.
- Remove capability definitions.
- Store immutable capability metadata.
- Validate capability registrations.
- Maintain capability indexes.
- Retrieve capabilities by identifier.
- Retrieve capabilities by category.
- Retrieve capabilities by tag.
- Search capabilities using supported filters.
- Enable or disable capabilities.
- Publish capability lifecycle events.

### Does NOT

- Resolve capability requests.
- Select providers.
- Execute capabilities.
- Apply permissions or policies.
- Manage runtime capability state beyond registration metadata.

> **Why a registry separate from resolution:** registering "what
> capabilities exist" is a Module-startup-time concern (every Module
> driver calls `register()` from its own `start()`); resolving "is
> this specific capability usable right now" is a per-Goal,
> planning-time concern (`CapabilityResolver`, §10). Splitting them
> means a Module can register a capability once and have every future
> Goal targeting it re-validated independently, without the registry
> itself needing any planning-time logic. **Called by:** every Module
> driver's `start()`/`stop()` (register/unregister); `CapabilityResolver.resolve()`
> (lookup); the REST `/api/v1/capabilities` handler, the `/capabilities`
> slash command, and the Coding Agent's `StandardCodingAgent` (read-only
> enumeration via `get_all()`).

------------------------------------------------------------------------

## 10. CapabilityResolver

### Purpose

Resolves capability requests into validated immutable capability
resolutions.

### Responsibilities

- Resolve capability definitions from the CapabilityRegistry.
- Validate resolved capability definitions.
- Reject disabled capabilities.
- Produce immutable CapabilityResolution objects.

### Does NOT

- Register or manage capabilities.
- Select providers.
- Evaluate resources.
- Evaluate policies.
- Execute capabilities.
- Route requests.
- Cache capability resolutions.
- Publish events.

> **Called by:** exclusively `Planner.plan()`, once per Goal, as the
> first of Planner's four per-Goal steps (see `PARIKA_Decision_Flow.md`
> §4.1). **Calls:** `CapabilityRegistry.get()`. This narrow scope --
> resolve, validate, reject if disabled, nothing else -- is what lets
> `CapabilityResolutionError`s surface as a clean `planning_failure`
> before any Task is ever created (Brain never even calls TaskManager
> for a Goal whose capability does not exist or is disabled).

------------------------------------------------------------------------

## 11. ContextManager

### Purpose

Maintains the authoritative registry of transient runtime Context
objects.

### Responsibilities

- Register contexts.
- Store transient runtime contexts.
- Retrieve contexts.
- Check whether contexts are registered.
- Replace contexts.
- Remove contexts.
- Enumerate contexts.
- Publish context lifecycle events.

### Does NOT

- Create contexts.
- Generate context identifiers.
- Store long-term memory.
- Manage workflows.
- Execute tasks.
- Manage scheduling.
- Manage knowledge.
- Interpret context metadata.

> **Implementation status:** unlike every other component above,
> **`ContextManager` is not constructed by `build_default_runtime()`**
> and has zero callers anywhere in `parika/` outside its own package
> and tests today -- the same "designed for, not yet wired" status as
> `WorkflowEngine` (§17), `Scheduler` (§20), `LifecycleManager` (§21),
> `MetricsManager` (§23), and `UpdateManager` (§26). `Goal` and
> `TaskRequest` both already carry an optional `context_id` field for
> exactly this purpose, and Planner/TaskManager already pass it through
> unchanged -- but neither calls `ContextManager` to create, validate,
> or look up the Context itself, matching this component's explicit
> "Does NOT: Create contexts" boundary. This is distinct from Brain's
> private `context_engine` subpackage (§29), which *is* live and
> unrelated to this component.

------------------------------------------------------------------------

## 12. MemoryManager

### Purpose

Stores and manages PARIKA's immutable memory records.

### Responsibilities

- Register memory records.
- Persist memory records.
- Retrieve stored memories.
- Update existing memories.
- Remove memories.
- Manage memory lifecycle.
- Validate memory operations.
- Publish memory lifecycle events.
- Self-report `memory.search.started/completed/failed` execution
  progress around `search()` (Phase 3.5b), through the `EventBus`
  already held at construction, as an independent activity -- never
  nested under any caller's tree; see §5 "Utilities".
- Score and rank memories for retrieval (`search()`, returning
  `tuple[ScoredMemory, ...]`), filter by scope/kind (`get_by_scope()`,
  `get_by_kind()`), track access recency (`touch()`), and identify
  read-only consolidation/pruning candidates (`consolidation_candidates()`,
  `prune()` -- both mechanical/deterministic selections that return
  memories for the caller to act on; neither summarizes or deletes
  anything `MemoryManager` was not explicitly asked to remove).

### Does NOT

- Perform semantic search. `search()`'s ranking is purely lexical --
  SQLite FTS5 `bm25()` blended with recency/importance/frequency/
  confidence weights (`[memory]` in `config/defaults.toml`, read
  through `Configuration` -- no parallel config system), never a
  vector/embedding similarity.
- Generate embeddings.
- Classify memories.
- Index documents.
- Manage knowledge repositories.
- Reason over memories. `consolidation_candidates()` never produces a
  summary itself -- turning several short-term memories into one
  `SUMMARY` memory requires an LLM call, which the caller (a future
  Brain/Interface reasoning layer) must perform, then write back via
  `register()`.
- Interpret memory content.

> **Implementation status:** wired into `build_default_runtime()`
> (`parika/interfaces/runtime.py`, backed by `data/memory.sqlite3`).
> Automatic preference detection from chat turns
> (`parika/interfaces/preference_detection.py`) exists as a rule-based
> helper but is **not** called by `InterfaceSession.save()` -- it was
> deliberately left unwired to avoid recording memories the user never
> explicitly requested; writing a `Memory` today always requires an
> explicit `MemoryManager.register()`/`remember()` call by a Tool,
> Module, or slash command (e.g. `/memory`).

> **Why immutable records, not a mutable profile:** an append-only
> `Memory` per fact (rather than one mutable "user profile" object)
> means every write is independently attributable (`origin`,
> `created_at`) and independently prunable/consolidatable, without ever
> risking one write silently clobbering another's provenance. **Called
> by:** the Memory Tool (`memory.remember`/`.search`/`.forget`
> capabilities), Brain's `assemble_context()` (§29), and the `/memory`
> slash command. **Calls:** its own `MemoryStorage`/SQLite layer and
> `EventBus.publish()` -- never another Core component.

------------------------------------------------------------------------

## 13. KnowledgeManager

### Purpose

Coordinates the lifecycle of knowledge sources and knowledge engines,
and orchestrates indexing and search across the PARIKA knowledge
system.

### Responsibilities

- Manage the lifecycle of `KnowledgeSource` objects.
- Register and unregister `KnowledgeEngine` implementations.
- Orchestrate knowledge indexing.
- Orchestrate knowledge search.
- Coordinate `KnowledgeStorage` and `KnowledgeEngine` interactions.
- Publish knowledge lifecycle and indexing events through the
  `EventBus`.
- Perform diagnostic logging for knowledge operations.
- Self-report `knowledge.search.started/completed/failed` execution
  progress around `search()` (Phase 3.5b), through the `EventBus`
  already held at construction, as an independent activity -- never
  nested under any caller's tree; see §5 "Utilities".
- Sort merged, cross-engine search results by each result's
  already-computed `score` and honor `SearchQuery.limit`/`offset` --
  pure bookkeeping over values the registered `KnowledgeEngine`s
  already produced, not a new scoring computation (see "Does NOT ...
  rank or score search results" below).
- Skip re-indexing a `KnowledgeSource` whose content is unchanged
  (`index_incremental(source_id, content_hash)`, comparing two opaque
  hash strings for equality -- the hash itself is always computed by
  the calling engine/driver, never by `KnowledgeManager`).

### Does NOT

- Store knowledge. `SqliteKnowledgeStorage`
  (`parika/core/knowledge_manager/sqlite_storage.py`) persists only
  `KnowledgeSource` rows (metadata about a source), never `Knowledge`
  content units themselves -- those are stored by each `KnowledgeEngine`
  in its own storage (e.g. `KnowledgeUnitStorage` for the Knowledge
  Indexing Module's engines, `CodingIndexStorage` for the Repository
  Intelligence Module's engine).
- Extract knowledge from sources.
- Implement indexing algorithms.
- Implement search algorithms.
- Parse or process source content.
- Rank or score search results (beyond the pure sort/paginate
  bookkeeping above -- every result's `score` is computed by the
  `KnowledgeEngine` that produced it).
- Cache knowledge or search results.
- Store user memories.
- Execute internet searches.
- Contain business logic specific to any knowledge source or engine.

> **Implementation status:** wired into `build_default_runtime()`
> (`parika/interfaces/runtime.py`), backed by `SqliteKnowledgeStorage`
> (`data/knowledge.sqlite3`). Two `KnowledgeEngine` implementations ship
> today, both registered as Modules (never inside Core, matching "Does
> NOT implement indexing algorithms"):
>
> - The **Knowledge Indexing Module** (`parika/modules/knowledge_indexing/`)
>   registers `DocumentKnowledgeEngine` (`DOCUMENTATION`/
>   `DOCUMENT_COLLECTION` sources; `.md`/`.txt`/`.rst`, paragraph-chunked)
>   and `CodeKnowledgeEngine` (`REPOSITORY`/`WORKSPACE` sources; Python
>   symbol extraction via the stdlib `ast` module). Both store their
>   `Knowledge` units in a shared, FTS5-indexed `data/knowledge_units.sqlite3`.
> - The **Repository Intelligence Module**
>   (`parika/modules/repository_intelligence/`) registers
>   `RepositoryKnowledgeEngine`, which also supports `REPOSITORY`/
>   `WORKSPACE` sources -- discovering every Git repository and detected
>   project beneath a workspace root, indexing every source file's
>   symbols directly into the Coding Tool's own `CodingIndexStorage`
>   (a plain shared object reference, not a Module-to-Module call), and
>   registering each repository's README as its own child
>   `DOCUMENTATION` source for `DocumentKnowledgeEngine` to index. Its
>   read-only `GitReader` collaborator reads Git metadata (current
>   branch, remote URL, recent commits) through exactly three fixed,
>   read-only `git` subcommands run via the existing Shell Tool's
>   `shell.execute` capability -- never a new Git library dependency,
>   never a mutating Git command. See `Module_Guide.md` §18.1-18.2 for
>   how the `coding`, `repository_intelligence`, and `knowledge_indexing`
>   Modules' load order resolves the resulting `REPOSITORY`/`WORKSPACE`
>   registration overlap (`KnowledgeEngineRegistry.resolve()` is a
>   first-match registry).

> **Why an engine registry rather than a fixed set of source kinds:**
> new knowledge domains are added by registering one more
> `KnowledgeEngine` at Module-startup time, never by `KnowledgeManager`
> growing a new `if source.kind is ...` branch -- the same "protocol +
> registry" extensibility shape used throughout this codebase
> (`ScoringRule`, `InferenceRule`, `SearchBackend`, `LanguageAnalyzer`).
> **Called by:** Brain's `assemble_context()` (§29) is the only caller
> of `search()` today; Module drivers call `register_engine()`/
> `register_source()` at startup. **Calls:** each registered
> `KnowledgeEngine`'s `index()`/`search()`, its own
> `SqliteKnowledgeStorage`, and `EventBus.publish()`.

------------------------------------------------------------------------

## 14. ProviderManager

### Purpose

Manages AI providers connected to PARIKA by maintaining the provider
registry, discovering available models, monitoring provider health,
and delegating request execution to provider-specific drivers.

### Responsibilities

- Register and unregister AI providers.
- Store and retrieve immutable Provider objects.
- Maintain the provider registry.
- Discover and update provider models.
- Monitor and refresh provider health.
- Delegate request execution to provider-specific drivers.
- Publish provider lifecycle events.
- Provide provider lookup and enumeration operations.

### Does NOT

- Decide which provider or model should be used. This remains true
  even with the Intelligent Model Selection Framework in place (see
  Planner's responsibilities above and
  [`Model_Selection_Framework.md`](Model_Selection_Framework.md)):
  Planner performs every selection decision by reading
  `ProviderManager.get_all()`; `ProviderManager` itself never scores,
  ranks, or chooses anything.
- Route requests between providers.
- Execute provider-specific API logic.
- Manage provider connection state transitions.
- Execute workflows or tasks.
- Implement retry, failover, or load-balancing logic.

> **Why a pure registry, deliberately not smarter:** keeping every
> provider-specific concern (auth, wire format, streaming, tool-call
> parsing) inside that provider's own `ProviderDriver` -- and keeping
> selection logic entirely inside Planner (§28) -- is what lets a new
> Provider be added by implementing exactly one interface
> (`ProviderDriver.discover_models()`/`.check_health()`/`.execute(model,
> request)`) with zero changes to `ProviderManager`, Planner, or any
> other Provider's code. Only one `ProviderDriver` ships today
> (`OllamaProviderDriver`, `parika/providers/ollama/`). The same
> boundary is why the Runtime Context Budget's provider-specific
> translation (e.g. `num_ctx`) lives only inside `OllamaProviderDriver`
> (`providers/ollama/wire.py`'s `build_options_payload()`) rather than
> in `ProviderManager` or Planner — Planner only ever sets the generic
> `RequestOptions.context_window_tokens` token count (see §28 above and
> `provider_manager/context_budget.py`), sized to cover the complete
> assembled prompt via `resolve_runtime_context_budget()`'s optional
> `required_prompt_tokens` input — itself read from `RequestOptions
> .estimated_prompt_tokens`, a value AI Context Engineering's Prompt
> Engineering responsibility measured once
> (`interfaces/ai_context/goal_builder.py`), never a value
> `ProviderManager` or `OllamaProviderDriver` compute themselves.
> **Called by:**
> `CapabilityExecutor.execute()` (dispatch) and `Planner._select_provider_model()`
> (`get_all()`, for scoring candidates) -- `Planner` never calls
> `execute()` itself. **Calls:** the registered `ProviderDriver`'s
> three methods above; nothing else.

------------------------------------------------------------------------

## 15. ToolManager

### Purpose

Maintains the authoritative runtime registry of deterministic tools
available to PARIKA and delegates tool execution to their associated
ToolDriver implementations.

### Responsibilities

- Register and unregister Tool objects.
- Maintain the runtime Tool registry.
- Associate each Tool with its ToolDriver.
- Retrieve and enumerate registered Tools.
- Delegate Tool execution to ToolDriver implementations.
- Publish Tool lifecycle and execution events.

### Does NOT

- Create Tool objects.
- Implement Tool execution logic.
- Manage AI providers.
- Select or route Tools.
- Execute workflows or tasks.
- Perform planning or scheduling.

> **Why symmetric with ProviderManager:** Tools and Providers are
> PARIKA's two execution backends (`ExecutionBackend.TOOL`/`.PROVIDER`),
> so `ToolManager` mirrors `ProviderManager`'s shape exactly -- a pure
> registry delegating to a driver, never deciding which one gets
> selected. The extension point is the `ToolDriver` Protocol
> (`execute(request: ToolRequest) -> ToolResponse`, one method) --
> implementing it and registering a `Tool` descriptor is the entire
> contract for adding a new deterministic capability. **Called by:**
> `CapabilityExecutor.execute()` (dispatch) and
> `Planner._select_tool()` (`get_all()`, for capability-matching).
> **Calls:** the registered `ToolDriver.execute()`; nothing else.

------------------------------------------------------------------------

## 16. ModuleManager

### Purpose

Maintains the authoritative runtime registry of PARIKA Modules and
coordinates their runtime lifecycle.

### Responsibilities

- Maintain the authoritative runtime registry of Modules.
- Register and unregister Modules.
- Retrieve and enumerate registered Modules.
- Retrieve active Modules.
- Start and stop registered Modules.
- Coordinate the runtime lifecycle of Modules.
- Maintain the operational state of Modules.
- Publish module lifecycle events through the EventBus.
- Delegate runtime execution to ModuleDriver implementations.
- Provide diagnostic logging for module lifecycle operations.

### Does NOT

- Discover Modules.
- Install or remove module packages.
- Execute module business logic.
- Register or resolve capabilities.
- Load or validate module configuration.
- Evaluate permissions.
- Select or manage AI providers.
- Coordinate workflows.
- Perform planning or routing.

> **Why a lifecycle coordinator separate from the drivers it runs:**
> `ModuleManager` owns only *when* a Module's `start()`/`stop()` runs
> and what state it is in -- registering Capabilities, Tools, and
> Providers is the `ModuleDriver`'s own job (the extension point:
> implement `start(self) -> None`/`stop(self) -> None`, register
> everything the Module owns in `start()`, unregister the same things
> symmetrically in `stop()`). This keeps a Module's actual behavior
> entirely inside its own package, so `ModuleManager` never needs to
> know what a Web Search Module or a Coding Module *does*, only that it
> can be started and stopped. **Called by:** `build_default_runtime()`
> (registers and loads all 15 built-in Modules), the `/modules` and
> `/reload` slash commands, and the REST `/api/v1/modules` endpoints.
> **Calls:** each registered `ModuleDriver.start()`/`.stop()`.

------------------------------------------------------------------------

## 17. WorkflowEngine

### Purpose

Coordinates the execution lifecycle of registered Workflows.

### Responsibilities

- Maintain the authoritative runtime registry of Workflow
  definitions.
- Register and unregister Workflows.
- Validate Workflow definitions before registration.
- Create and manage Workflow Execution instances.
- Coordinate Workflow execution.
- Manage Workflow execution lifecycle (start, pause, resume, complete,
  fail, cancel).
- Track current execution state and active Step.
- Coordinate Workflow progression between Steps.
- Publish Workflow lifecycle and Step execution events through
  EventBus.
- Perform diagnostic logging.

### Does NOT

- Discover or generate Workflows.
- Persist Workflow definitions or execution history.
- Schedule Workflow execution.
- Plan or optimize Workflows.
- Execute Capabilities directly.
- Resolve Capabilities.
- Execute Tools, Modules, or Providers directly.
- Manage Contexts.
- Manage Memory or Knowledge.
- Manage Resources.
- Evaluate Permissions or Policies.

> **Why a distinct component from Planner's dependency-ordered Goals:**
> a flat, dependency-ordered `Goal` list (Planner's `ExecutionPlan`)
> can express "run these in this order, skip dependents of a failure,"
> but not pause/resume across a genuinely long-running, stateful,
> multi-step process -- `WorkflowEngine` exists for that different
> shape of execution, once its step-execution engine is implemented
> (below), without requiring Planner or Brain to grow that
> responsibility themselves.

> **Implementation note:** step execution (`_execute_step`) and
> execution creation (`_create_execution`) are not yet implemented in
> the current codebase; `execute()` and a real `resume()` therefore
> currently raise `NotImplementedError` for any registered Workflow.
> Registration, pause/cancel state transitions on an already-created
> execution, and the completion/failure/cleanup paths are fully
> implemented and tested. This is a known, tracked gap — see the
> project's test suite (`tests/core/workflow_engine/`) for the exact
> current behavior. `WorkflowEngine` is additionally **not constructed
> by `build_default_runtime()`** today, the same "not wired" status as
> `Scheduler` (§20), `ContextManager` (§11), `LifecycleManager` (§21),
> `MetricsManager` (§23), and `UpdateManager` (§26).

------------------------------------------------------------------------

## 18. CapabilityExecutor

### Purpose

Executes resolved capabilities by delegating execution to the
appropriate execution backend.

### Responsibilities

- Validate capability execution requests.
- Execute resolved capabilities.
- Delegate execution to ToolManager or ProviderManager.
- Measure execution duration.
- Publish capability execution lifecycle events
  (`capability.execution.started/completed/failed`), optionally
  carrying the caller-supplied `task_id` (Phase 3.5b) that correlates
  one execution to its owning `TaskManager` `Task` and to its own
  Started/Completed/Failed counterpart -- `None` when execution is
  requested without one.
- Return execution results.
- Wrap backend execution failures.

### Does NOT

- Resolve capabilities.
- Select execution backends.
- Select provider models.
- Build backend execution requests.
- Interpret execution results.
- Execute tools directly.
- Execute providers directly.
- Manage task lifecycle.
- Build execution plans.
- Schedule execution.

> **Why this thin layer exists at all:** without it, `TaskManager`
> would need an `if backend is TOOL: call ToolManager else: call
> ProviderManager` branch of its own, coupling task lifecycle to
> backend dispatch. Instead, `CapabilityExecutor` is the one place
> that knows both backends exist, letting `TaskManager` stay backend-
> agnostic (it only ever calls `CapabilityExecutor.execute()`) and
> letting execution-timing/event-publishing be implemented exactly
> once regardless of which backend actually ran. **Called by:**
> exclusively `TaskManager.execute()`. **Calls:** `ToolManager.execute()`
> or `ProviderManager.execute()`, based on `execution_request.target.backend`
> -- never both, never neither.

------------------------------------------------------------------------

## 19. TaskManager

### Purpose

Creates, executes, tracks, and manages the lifecycle of executable
tasks.

### Responsibilities

- Create tasks.
- Execute tasks.
- Delegate capability execution to CapabilityExecutor.
- Pause tasks.
- Resume tasks.
- Cancel tasks.
- Complete tasks.
- Fail tasks.
- Track task status.
- Publish task lifecycle events.

### Does NOT

- Build execution plans.
- Resolve capabilities.
- Build capability execution requests.
- Select execution backends.
- Execute capabilities directly.
- Execute tools directly.
- Execute providers directly.
- Schedule execution.

> **Why Task lifecycle is a separate concern from planning:** a
> `Task`'s pending/running/completed/failed/cancelled/paused states,
> and its retry semantics, apply identically no matter which Goal or
> Plan produced it -- separating this from `Planner`/`Brain` means a
> future caller (a Scheduler-triggered job, a Workflow step) could
> create and execute Tasks directly without needing Planner at all,
> since nothing about Task lifecycle depends on how the
> `CapabilityExecutionRequest` was produced. **Called by:** exclusively
> `Brain._supervise()`, once per `PlanStep`, in Planner's already
> dependency-ordered sequence. **Calls:** `CapabilityExecutor.execute()`
> -- the only place `TaskManager` talks to it (§18).

------------------------------------------------------------------------

## 20. Scheduler

### Purpose

Schedules work to execute at the appropriate time.

### Responsibilities

- Timers.
- Delayed execution.
- Scheduled execution.
- Recurring jobs.
- Trigger management.

### Does NOT

- Execute business logic.
- Plan workflows.

> **Implementation status:** fully implemented and tested
> (`parika/core/scheduler/`, `tests/core/scheduler/`) but, unlike every
> other component in this document, **not constructed by
> `build_default_runtime()`** -- `ParikaRuntime` has no `scheduler`
> field, and no Module, Tool, or Provider in this codebase currently
> schedules a job through it. It is a complete, available building
> block with zero production call sites today, the same "designed for,
> not yet wired" status `WorkflowEngine` (§17) already documents for
> its own step-execution engine. See `Integration_Checklist.md` §9 for
> how a future Module would use it once one needs time-based triggers.

------------------------------------------------------------------------

## 21. LifecycleManager

### Purpose

Controls the lifecycle of the PARIKA application.

### Responsibilities

- Startup.
- Initialization.
- Shutdown.
- Restart.
- Reload.

### Does NOT

- Execute application logic.
- Manage runtime state.

> **Implementation status:** `LifecycleManager` is **not constructed
> anywhere in `parika/` today** -- it exists as a complete, tested
> class with a real dependency on `StateManager` (its `start()`/
> `stop()`/`restart()`/`reload()` methods call `StateManager`'s
> setters, §7), but nothing instantiates it. `build_default_runtime()`
> and `shutdown_runtime()` (`parika/interfaces/runtime.py`) perform
> the equivalent startup/shutdown sequencing today by direct,
> hand-written construction/teardown calls rather than through this
> component. Same "designed for, not yet wired" status as
> `WorkflowEngine` (§17), `Scheduler` (§20), `ContextManager` (§11),
> `MetricsManager` (§23), and `UpdateManager` (§26).

------------------------------------------------------------------------

## 22. HealthManager

### Purpose

Monitors the operational health of PARIKA.

### Responsibilities

- Health checks.
- Heartbeats.
- Failure detection.
- Component health reporting.
- Recovery coordination.

### Does NOT

- Monitor hardware resources.
- Collect performance metrics.

> **Implementation status:** constructed in `build_default_runtime()`,
> and `.register()` is genuinely called by every built-in Module
> driver's `start()` (a health check per Module -- see e.g.
> `parika/modules/repository_intelligence/driver.py`,
> `parika/modules/shell/driver.py`, and every other Module driver).
> However, **nothing calls `.run_check()`/`.run_all_checks()` outside
> `HealthManager`'s own package today** -- not the `/status` slash
> command, not the REST `/api/v1/health`/`/status` endpoints (which
> return static/`StateManager`-derived data instead, §7). Every
> registered health check is real and callable, but no Interface
> currently triggers one.

------------------------------------------------------------------------

## 23. MetricsManager

### Purpose

Collects runtime metrics for monitoring and optimization.

### Responsibilities

- Performance metrics.
- Timing measurements.
- Usage statistics.
- Counters.
- Runtime measurements.

### Does NOT

- Write application logs.
- Monitor component health.

> **Implementation status:** constructed in `build_default_runtime()`
> but, like `LifecycleManager`/`ContextManager`/`UpdateManager`, has
> **zero callers anywhere in `parika/` outside its own package and
> tests** -- no Tool, Module, or Interface currently records a counter,
> timing, or gauge through it.

------------------------------------------------------------------------

## 24. PolicyEngine

### Purpose

Evaluates every policy-driven decision within PARIKA.

### Responsibilities

- Policy evaluation.
- Rule execution.
- Conflict resolution.
- Policy enforcement decisions.

### Does NOT

- Store policies.
- Execute protected operations.

> **Relationship to workspace permissions:** `PolicyEngine` (stateless,
> context-dependent rules supplied by the caller) and
> `PermissionManager`/its Workspace Permission Manager extension
> (static, per-workspace grants, see PermissionManager's entry above)
> remain deliberately independent. Reading any file on the host is,
> by design, never checked by the Workspace Permission Manager; if an
> operator ever needs to additionally restrict reads (e.g. denying a
> specific sensitive path), that is a `PolicyEngine` rule attached to
> the relevant Goal, not a change to PermissionManager.

> **Why stateless:** `PolicyEngine` never stores a `PolicyRule` --
> every rule it evaluates is supplied fresh, on the `Goal` itself, by
> whatever built that Goal. This is the concrete meaning of "Policies
> define behavior instead of code" (Architecture Spec §8): PARIKA does
> not yet ship a first-class "attach the right rule to every matching
> Goal automatically" mechanism, so if a Goal carries no rules, the
> default effect (`ALLOW`) wins and nothing is blocked -- no policy
> attached means no restriction, by design, not by omission. **Called
> by:** exclusively `Planner.plan()`, once per Goal, evaluating
> `goal.policy_rules` against a context built from the Goal and the
> `ResourceManager` snapshot already captured that same `plan()` call.
> **Calls:** each supplied `PolicyRule`'s own predicate; nothing else.

------------------------------------------------------------------------

## 25. PermissionManager

### Purpose

Determines whether an operation is authorized.

### Responsibilities

- Authorization.
- Permission validation.
- Confirmation requirements.
- Access control.
- Workspace-scoped permission delegation (Once/Session/Permanent/Deny)
  through the Workspace Permission Manager extension described below,
  composed entirely from this component's own existing `grant()`/
  `revoke()`/`check()` public methods.

### Does NOT

- Define policies.
- Execute operations.
- Analyze, parse, or restrict what an authorized operation actually
  does once it is allowed to run (see "Execute permission is scoped,
  not analytical" below).

> **Called by:** today, `PermissionManager`'s own base `grant()`/
> `revoke()`/`check()` methods are called only from inside its own
> `WorkspacePermissionManager` extension (below) -- no Tool, Module, or
> Interface calls the base API directly. `WorkspacePermissionManager`
> itself is called by the Filesystem Module and the Shell Module.
> **Calls:** the registered `WorkspacePermissionPrompt` (an Interface-
> supplied Protocol implementation) when an interactive decision is
> needed, and `RuntimeTrustWriter`/`tomlkit` to persist a "Permanent"
> grant.
>
> **Workspace Permission Manager (implemented extension):** this is not
> a new Core component. It is a small set of additional files inside
> the existing `parika/core/permission_manager/` package
> (`workspace_operation.py`, `workspace_permission_scope.py`,
> `workspace_permission_decision.py`, `workspace_permission_prompt.py`,
> `workspace_trust_store.py`, `workspace_permission_manager.py`) that
> compose `PermissionManager`'s existing public API without changing
> any existing method signature, so that every present and future
> component that touches a workspace (the Filesystem Tool and the
> Shell Tool today; a future Coding Tool, Image Tool, Video Tool, Audio
> Tool, ...) asks this one shared authority instead of implementing its
> own permission logic. Constructed once in `build_default_runtime()`
> (`parika/interfaces/runtime.py`) and shared by every Module that
> needs it.
>
> - **What a workspace is:** a workspace is the directory containing
>   the target path being accessed, unless a different workspace
>   resolution strategy is introduced in the future. Workspace paths
>   are never hardcoded anywhere in PARIKA or its documentation - any
>   specific directory shown as an example (in this document, in
>   `Tool_Guide.md`, or in the README) is illustrative only. The actual
>   set of trusted workspaces always comes from configuration
>   (`[workspace].default_workspace`, `[filesystem].trusted_workspaces`)
>   or from a user's own interactive "Always trust" decision at
>   runtime.
> - **Permission scopes:** `Once` (authorizes the current call only;
>   never stored), `Session` (a plain `grant()` call, active for the
>   lifetime of the `PermissionManager` instance - today, one CLI
>   process/`InterfaceSession` - matching "remains active until PARIKA
>   exits"), `Permanent` (the same `grant()` call, plus persisting the
>   workspace into `trusted_workspaces` so it survives restart - see
>   below), `Deny` (rejects the current call only; nothing is stored,
>   so the same workspace is asked about again on its next access).
> - **Namespacing:** every workspace-derived `subject_id` passed to
>   `grant()`/`check()` is namespaced as `workspace:<canonical-path>`
>   (the fully resolved, absolute path) so it can never collide with
>   any other kind of subject id (a Module id, a Tool id, ...) a future
>   caller registers in the same shared registry.
> - **Interactive prompting:** delegated through a `Protocol` defined
>   in this package and implemented by whichever Interface is active
>   (e.g. the CLI renders the `Allow once` / `Allow for this session` /
>   `Always trust this workspace` / `Deny` choices) - the same
>   dependency-inversion shape already used for `ExperienceSource`
>   (`parika/core/planner/model_selection/experience_source.py`), so
>   Core still never depends on a concrete Interface. No prompt
>   registered (e.g. a future headless entry point) fails closed
>   (treated as `Deny`), never blocks indefinitely.
> - **Concurrent request coalescing:** at most one interactive prompt
>   is ever in flight per `(workspace, operation)` pair at a time. If a
>   second request for the same pair arrives while a prompt is already
>   pending, it does not produce a second prompt - it waits for, and
>   is resolved by, the one pending prompt's decision.
> - **Persistence of "Always trust":** writes the workspace into
>   `config/runtime.toml` (the existing, already-documented
>   auto-managed configuration layer - see Configuration's entry above)
>   using `tomlkit`, which preserves existing formatting and comments.
>   The write is atomic: content is written to a temporary file in the
>   same directory and moved into place with `os.replace()` - the same
>   atomic-write pattern the Filesystem Tool's own `write()` operation
>   already uses - so a crash or concurrent read can never observe a
>   partially written `runtime.toml` or corrupt it. This never mutates
>   `Configuration` itself, which remains read-only and loaded exactly
>   once per process, per its own entry above; the persisted trust
>   takes effect immediately in the current process via the in-memory
>   `grant()` call, and for every future run the next time
>   `Configuration.load()` reads `runtime.toml` from disk.
> - **Execute permission is scoped, not analytical:** `Execute`
>   authorizes only "commands may be run with this directory as their
>   working directory" - it never parses, inspects, or restricts what a
>   command actually does once authorized. See
>   `docs/development/Tool_Guide.md` §22.2 for the full rationale and
>   why a Shell Tool must not attempt to work around this by parsing
>   commands itself.
> - **Reads are out of scope for this extension:** per the current
>   System Interaction Foundation requirements, reading, searching, and
>   inspecting files is always allowed anywhere on the host and is
>   never checked by the Workspace Permission Manager. If additional
>   read restrictions are ever required, they belong to `PolicyEngine`
>   (a context-dependent rule attached to a Goal - see PolicyEngine's
>   entry below), not to PermissionManager or this extension.
>
> See `docs/development/Tool_Guide.md` §22-23 for how the Shell Tool
> and the Filesystem Tool each consume this extension, and
> `docs/architecture/PARIKA_Decision_Flow.md` §14 for the end-to-end
> decision flow.

------------------------------------------------------------------------

## 26. UpdateManager

### Purpose

Coordinates updates throughout the PARIKA ecosystem.

### Responsibilities

- Core updates.
- Module updates.
- Provider updates.
- Tool updates.
- Configuration migrations.

### Does NOT

- Install arbitrary software.
- Execute update policies.

> **Implementation status:** `UpdateManager` is **not constructed
> anywhere in `parika/` today** and has no callers -- the same
> "designed for, not yet wired" status as `WorkflowEngine` (§17),
> `Scheduler` (§20), `ContextManager` (§11), and `LifecycleManager`
> (§21). No update mechanism (Core, Module, Provider, or Tool) exists
> in this codebase yet; PARIKA is updated today by pulling new source
> and restarting the process (`docs/guides/Running.md` §12.2).

------------------------------------------------------------------------

## 27. Router

### Purpose

Routes validated requests to the appropriate execution path.

### Responsibilities

- Request routing.
- Execution path selection.
- Dispatch coordination.

### Does NOT

- Plan execution.
- Execute business logic.

> **Why a general dispatch mechanism, not an HTTP router:** despite
> the name, `Router` is a plain matcher/handler registry (each `Route`
> carries a `matcher` predicate and a `handler`) with no knowledge of
> HTTP, Brain, or any specific execution path -- it exists so that
> *any* future component needing "pick the right handler for this
> request, by priority" (today, the REST/WebSocket API layer; a future
> `TaskManager`-vs-`WorkflowEngine` choice per §5 of
> `PARIKA_Decision_Flow.md`) can reuse one tested dispatch mechanism
> instead of writing its own if/elif chain.
>
> **Implementation status and interactions:** `Router` is constructed
> **only by the Server Platform** (`parika/server/app.py`, one instance
> per running server process) and is **not part of `ParikaRuntime`/
> `build_default_runtime()`** -- the PARIKA Console never constructs
> or uses a `Router` at all; it calls `Brain.handle()`/Core managers
> directly, in-process. **Called by:** every REST route handler in
> `parika/api/routers/` (`.dispatch()`), each passing one of the
> internal `*Request` dataclasses from `parika/api/requests.py`.
> **Calls:** whatever handler function was registered for the matched
> `Route` (`parika/api/router_bindings.py`'s handlers, which in turn
> call the real Core managers -- `Brain`, `ToolManager`,
> `ModuleManager`, etc.). Brain's own pipeline (`Planner → TaskManager`)
> never goes through `Router` -- see `PARIKA_Decision_Flow.md` §5 for
> exactly when Router would become relevant to Brain's own dispatch.

------------------------------------------------------------------------

## 28. Planner

### Purpose

Transforms user goals into executable plans.

### Responsibilities

- Goal decomposition.
- Execution planning.
- Dependency ordering.
- Execution strategy, including *intelligent, constraint-based*
  Provider/model selection (see
  [`Model_Selection_Framework.md`](Model_Selection_Framework.md)):
  Planner derives provider-independent `ExecutionRequirements` from a
  Goal - including a generic Task Classification step that resolves
  the required specializations/capabilities/modalities/execution
  features for the Goal's task, never a provider or model name -
  **filters** every registered Provider's models down to the ones
  actually capable of the task, and only then **ranks** the surviving
  candidates against `[model_selection]` configuration, selecting the
  highest-scoring match. This is the same "execution strategy"
  responsibility Planner has always had, made smarter and correctness-
  first (an unsuitable model can never outrank a suitable one on
  performance alone); it does not change what Planner is responsible
  for, and it never becomes a ProviderManager responsibility (see
  ProviderManager's "Does NOT" list below).
- Computing the Runtime Context Budget for the selected model, once
  selection completes: `provider_manager.context_budget
  .resolve_runtime_context_budget()` narrows the selected model's own
  `ModelLimits.context_window` (Model Capabilities) by the
  `[context_engine]` configuration ceiling and configured
  reserved-for-response/safety-reserve token counts — then grows that
  window, never below the selected model's own true `context_window`
  ceiling, to cover `read_estimated_prompt_tokens(backend_request)`:
  the complete, already-assembled prompt's own measured token size,
  read from the just-built `ProviderRequest`'s generic
  `RequestOptions.estimated_prompt_tokens` field. That field was
  already set by AI Context Engineering's Prompt Engineering
  responsibility (`interfaces/ai_context/goal_builder.py`) when it
  built `backend_request`, moments earlier in this same method —
  Planner never measures a prompt itself, and never inspects any
  provider-specific field to derive one; it only ever reads an
  already-supplied, provider-independent integer, exactly like every
  other `RequestOptions` field. Planner applies the result onto the
  built `ProviderRequest`'s generic `RequestOptions
  .context_window_tokens` field (§4.4 of `PARIKA_Decision_Flow.md`) —
  the same pattern already used to apply the `reasoning` preference.
  This keeps every request's effective context window dynamically
  derived from both the actual selected model and the actual assembled
  prompt, instead of a Provider's own hardcoded default or a fixed
  ceiling blind to what AI Context Engineering actually assembled,
  without AI Context Engineering or Brain ever needing to know a
  Provider exists.
- Optionally score a candidate model by its historical outcome rate for
  a capability/provider/model combination, via one more `ScoringRule`
  (`ExperienceRule`, default weight `0`, opt-in) reading an
  `ExperienceSource` Protocol that Planner's own package defines
  (`parika/core/planner/model_selection/experience_source.py`) and an
  optional `experience_source` constructor parameter supplies. The
  Protocol has a single method,
  `aggregate_outcome_rate(capability_id, provider_id, model_id) -> float | None`,
  and degrades to a neutral score when no source is supplied or no data
  exists yet -- identical in shape to every other optional
  `ProviderModel.metadata` signal.
- Optionally score a candidate model by a per-request routing
  recommendation, via one more `ScoringRule` (`RoutingRecommendationRule`,
  default weight `20`, see
  [`Model_Selection_Framework.md`](Model_Selection_Framework.md) §6.3)
  reading `ExecutionRequirements.metadata["candidate_models"]` -- an
  AI-assisted signal supplied by the routing model itself (the same
  model already selected for `chat.respond`), never a new selection
  concept: Planner's filtering/scoring/final-selection responsibility
  is entirely unchanged, and the recommendation can never select a
  candidate `filtering.py` already rejected. This is deliberately not
  a first-class `ExecutionRequirements` field, since a recommendation
  is not a requirement (§4 of `Model_Selection_Framework.md`).
- Optionally short-circuit scoring for the *routing* Goal only (the
  Goal marked `Goal.metadata[ROUTING_GOAL_METADATA_KEY]`, set only by
  `interfaces/ai_context/goal_builder.build_chat_goal()`) when
  `[routing_model] mode = "fixed"` is configured, via
  `model_selection.select_fixed_routing_model()` -- see
  [`Model_Selection_Framework.md`](Model_Selection_Framework.md) §14.
  This is purely a latency optimization for the routing decision: the
  configured model still passes through the exact same, unmodified
  `filtering.evaluate_hard_requirements()` pipeline, an unavailable
  configured model logs a warning and falls back to the unmodified
  `mode = "auto"` scoring path automatically, and worker model
  selection (every Goal without that marker) is completely unaffected
  either way. Default (`mode = "auto"`, or `[routing_model]` absent
  entirely) is byte-for-byte the same selection Planner has always
  performed.

### Does NOT

- Execute tasks.
- Route requests.
- Own the Experience data itself. The concrete implementation
  (`ExperienceStore`, recording `task.completed`/`task.failed` and
  `capability.execution.completed`/`.failed` events into its own
  SQLite storage) lives in `parika/modules/experience/` -- a Module,
  not Core, since it has exactly one producer (events Core already
  publishes) and one consumer (Planner's own scoring rule). Planner's
  source file never imports `parika/modules/experience/`; only
  `runtime.py` (the composition root) knows about both sides.

> **Why Planner, not Brain, decomposes an execution strategy:** Brain's
> job is supervising *whether* Goals succeed; Planner's is deciding
> *how* each one will be attempted. Keeping that decision in one place
> is what makes "why was model X chosen over model Y" answerable from
> a single component's logs (`Model_Selection_Framework.md` §10)
> instead of being scattered across whichever component happened to
> need a backend. **Called by:** exclusively `Brain.handle()`, once per
> request, with every Goal already dependency-ordered by the caller.
> **Calls:** `CapabilityResolver.resolve()`, `ResourceManager
> .get_resource_snapshot()`, `PolicyEngine.evaluate()`,
> `ProviderManager.get_all()`/`ToolManager.get_all()` (read-only
> enumeration for scoring/matching -- never their `execute()` methods).
> Planner never executes anything itself; it only ever returns an
> `ExecutionPlan` to Brain.

------------------------------------------------------------------------

## 29. Brain

### Purpose

Acts as PARIKA's central orchestration engine.

### Responsibilities

- Receive user requests.
- Coordinate Core components.
- Supervise execution.
- Produce final responses.
- Maintain overall system intelligence.
- Self-publish the single root of execution-progress reporting
  (Phase 3.5b): one `brain.execution` tree per `handle()` call
  (`brain.planning` and `brain.execute_goal` children), through an
  optional `event_bus` constructor parameter -- see §5 "Utilities"
  and §4 "EventBus"'s Channel Catalog. Brain is the one component
  every present and future caller of `handle()` passes through
  (the Console today; a Scheduler, WorkflowEngine, or Automation
  caller tomorrow), so this is the single place that guarantees
  consistent execution-progress reporting without any caller
  constructing its own tree. Omitting `event_bus` leaves every other
  `handle()` behavior completely unchanged.
- Optionally assemble retrieval-based context (`assemble_context()`)
  and deterministically compact conversation history (`compact()`)
  through a private `brain/context_engine/` subpackage -- the same
  "component privately owns a subpackage" pattern Planner already
  established with `model_selection/`. Both methods are **opt-in and
  never called automatically by `handle()`**: `assemble_context()`
  calls `MemoryManager.search()`/`KnowledgeManager.search()` and
  greedily packs the highest-score-per-token results into a
  `TokenBudget` (`[context_engine]` in `config/defaults.toml`);
  `compact()` deterministically keeps the system message and as many
  of the most recent turns as fit within that same `TokenBudget`,
  replacing dropped middle turns with a placeholder -- never an LLM
  call. Neither method bounds how much it includes by a fixed entry
  or turn count (Phase A.5): both are driven entirely by
  `TokenBudget.usable_tokens`, so a larger Runtime Context Budget (a
  selected model with a bigger context window) surfaces more
  Memory/Knowledge/history content, and a smaller one surfaces less.
  Abstractive summarization, if wanted, is the caller's
  responsibility: build an explicit Goal targeting an LLM capability
  and submit it through the unchanged `handle()` pipeline like any
  other Goal.

### Does NOT

- Replace specialized Core components.
- Own responsibilities assigned to other managers.
- Subscribe to the EventBus for any other component's events --
  Brain only ever publishes its own `brain.execution` tree, never
  reacts to events.
- Call a Provider directly from `context_engine`. Compaction's default
  behavior is mechanical (position/recency/existing-score selection),
  never content interpretation.

> **Implementation status:** `assemble_context()`/`compact()` are live,
> tested, and opt-in (`parika/core/brain/context_engine/`).
> `assemble_context()` is wired into the live `chat.respond` pipeline's
> default path (`interfaces/ai_context/context_builder
> .assemble_context_messages()`, called from `InterfaceSession
> ._submit_text()` every turn). `compact()` is not wired into that
> pipeline today -- a caller (e.g. a future Interface enhancement)
> must invoke it explicitly before building a Goal's inputs.

> **Why orchestration lives in exactly one component:** every present
> and future caller -- the Console today; the REST/WebSocket API layer;
> a Scheduler, WorkflowEngine, or Automation caller tomorrow -- must
> get the same guarantees (planning-failure capture, dependency-aware
> execution, consistent progress reporting) with zero duplicated logic,
> which is only possible if there is exactly one place those guarantees
> are implemented. This is also why `Brain.handle()` never raises for
> pipeline failures (`PARIKA_Decision_Flow.md` §2): a shared
> orchestrator that could crash on any Goal's failure would make every
> caller responsible for defensive error handling Brain should own once.
> **Called by:** `InterfaceSession.submit_text()` (the Console and the
> API layer's normal chat path), `OllamaProviderDriver`'s
> `ToolCallResolver` (a *nested* re-entrant call when a model requests
> a tool), and `StandardCodingAgent` (also nested, when the Coding
> Agent Tool submits its own plan steps as Goals) -- in every nested
> case, still through the same unmodified `handle()`, never bypassing
> Planner. **Calls:** `Planner.plan()` and, per Goal,
> `TaskManager.create()`/`.execute()`.

------------------------------------------------------------------------

## Appendix: PARIKA Console (Interface Layer, not a Core component)

> This document's scope is "every Core component" (see the header
> above). The PARIKA Console is deliberately **not** Core -- per the
> Architecture Specification's Dependency Rules, it is an Interface
> that communicates only with Core, and Core never depends on it. It
> is documented here, immediately after Brain, only because Phase
> 3.5b's execution-progress work spans both Brain (Core) and the
> Console (Interface layer), and because the Console is otherwise
> undocumented in this file's numbered Core sequence. It is
> intentionally excluded from the numbered 1-29 list and from the
> Quick Lookup Table's Core count.

### Purpose

PARIKA's native, in-process administration console (`parika/console/`,
formerly `parika/interfaces/cli/`) -- bundled with the server,
communicating directly with Core exactly like the CLI always has. It
is not an external client and is not routed through, or limited by,
the REST/WebSocket API layer (`parika/api/`); it is not subject to
client authentication or rate limiting. It is intended for
administration, debugging, development, diagnostics, recovery, and
server management, and is PARIKA's primary administration interface.
See `docs/architecture/PARIKA_Architecture_Specification_v1.0.md`
("Architectural Boundary" section) for the distinction between the
Console and future external clients (Desktop, Web, Android, iOS,
Voice, a future CLI client), which will communicate exclusively
through `/api/v1`.

### Responsibilities

- Provide an interactive REPL: Markdown rendering, ANSI colors,
  command history, multiline input, graceful `Ctrl+C`/`Ctrl+D`
  handling.
- Stream the model's own answer tokens as they arrive
  (`StreamingPrinter`).
- Render live execution-progress events (Phase 3.5b,
  `progress_view.ConsoleProgressRenderer`): subscribes once, for the
  process lifetime, to the generic `progress.*` channels plus the
  existing `capability.execution.*` and `tool.executed`/
  `tool.execution_failed` channels, translating each into one status
  line -- never fabricating a status message on another component's
  behalf.
- Dispatch built-in slash commands (`parika/interfaces/commands/`),
  which read other Core managers directly for read-only introspection.
- Construct its own `ParikaRuntime` via `build_default_runtime()`, the
  same composition root every Interface uses.

**Extension point:** new slash commands are added to `CommandRegistry`
(`parika/interfaces/commands/registry.py`, `builtin.py`) as a
`CommandSpec`/`CommandHandler` pair — the Console itself never needs a
new branch for a new command, matching the same "protocol/registry,
never a growing if/elif chain" shape used throughout this codebase.

### Does NOT

- Call the REST/WebSocket API layer, ever, by design -- see the
  cancelled "Server Console" proposal note in
  `docs/guides/Running.md` section 12.7.
- Contain business logic: normal text is handed to
  `InterfaceSession.submit_text()`, which builds a `BrainRequest` and
  submits it to Brain; slash commands never call Brain.
- Fabricate artificial "loading"/"thinking" progress messages -- only
  real, already-reported execution-progress events are rendered.

------------------------------------------------------------------------

## Appendix: Session Persistence (Interfaces layer, not a Core component)

> Documented here for the same reason as the Console appendix above:
> it is Interfaces-layer infrastructure (`parika/interfaces/session_store.py`),
> not Core, so it is excluded from the numbered 1-29 list, but it is the
> concrete implementation of the "Session-wise Chat History" work this
> document's Memory/Knowledge sections above cross-reference.

`SqliteSessionStore` persists `InterfaceSession` conversation history to
`data/sessions.sqlite3` (`sessions` + `session_messages` tables, an
FTS5-indexed `session_messages_fts` for `/sessions search`). It is
entirely opt-in: `InterfaceSession(runtime, session_store=None)` (the
default) behaves exactly as it always has, in-memory only, for the
lifetime of the process. When a store is supplied, `InterfaceSession
.save()`/`.load()`/`.list_sessions()` persist and restore a session's
title, summary, workspace path, and full message history across runs.
Automatic preference detection from saved turns
(`parika/interfaces/preference_detection.py`) exists as a rule-based
helper but, like `MemoryManager`'s own automatic recording (§12), is
**not** wired into `save()` -- writing a Memory always requires an
explicit call today.

**Why this is Interfaces-layer state, not a Core component:** a
conversation session belongs to whichever Interface is talking to the
user (the Console today; the REST/WebSocket API layer, keyed by
`session_id`) -- Brain and Planner never need to know a session exists
at all, since every turn still reaches `Brain.handle()` as an ordinary
`BrainRequest`. Making this a Core component would give Core a concept
(a "conversation") that only ever has meaning to the layer presenting
it to a user.

------------------------------------------------------------------------

# Quick Lookup Table

The **Live?** column is a fast at-a-glance summary of each component's
"Implementation status"/"Interactions" note above -- read that
component's own section for the verified detail. **Live** means
`build_default_runtime()` constructs it *and* something outside its
own package actually calls it today. **Constructed, unused** means it
is wired into the runtime but has no real caller yet. **Not
constructed** means nothing in `parika/` instantiates it at all.

| # | Component | One-line purpose | Live? |
|---|---|---|---|
| 1 | Configuration | Single source of truth for configuration | Live |
| 2 | ServiceContainer | Central registry for shared singleton services | Live |
| 3 | Logger | Centralized logging infrastructure | Live |
| 4 | EventBus | Synchronous in-process publish/subscribe | Live |
| 5 | Utilities | Shared namespace for reusable utility modules | Live |
| 6 | Security | Shared namespace for low-level security modules | Empty by design |
| 7 | StateManager | Authoritative operational runtime state | Live (getters only) |
| 8 | ResourceManager | On-demand hardware/OS/filesystem information | Live |
| 9 | CapabilityRegistry | Authoritative registry of capability definitions | Live |
| 10 | CapabilityResolver | Resolves capability requests into resolutions | Live |
| 11 | ContextManager | Registry of transient runtime Context objects | Not constructed |
| 12 | MemoryManager | Stores and manages immutable memory records | Live |
| 13 | KnowledgeManager | Orchestrates knowledge indexing and search | Live |
| 14 | ProviderManager | Registry and health/model discovery for AI providers | Live |
| 15 | ToolManager | Registry and execution delegation for deterministic Tools | Live |
| 16 | ModuleManager | Registry and lifecycle coordination for Modules | Live |
| 17 | WorkflowEngine | Coordinates multi-step Workflow execution | Not constructed (`execute()` also raises `NotImplementedError` even if constructed) |
| 18 | CapabilityExecutor | Executes resolved capabilities via Tool/Provider backends | Live |
| 19 | TaskManager | Creates, executes, and tracks Task lifecycle | Live |
| 20 | Scheduler | Timers, delayed/recurring execution | Not constructed |
| 21 | LifecycleManager | Application startup/shutdown/restart/reload | Not constructed |
| 22 | HealthManager | Health checks, heartbeats, recovery coordination | Live (`.register()` only; checks never run) |
| 23 | MetricsManager | Counters, timings, usage statistics | Constructed, unused |
| 24 | PolicyEngine | Evaluates policy-driven decisions | Live |
| 25 | PermissionManager | Authorization and access control | Live (via its Workspace extension) |
| 26 | UpdateManager | Coordinates Core/Module/Provider/Tool updates | Not constructed |
| 27 | Router | Routes validated requests to execution paths | Live (API layer only; not part of `ParikaRuntime`) |
| 28 | Planner | Transforms Goals into executable plans | Live |
| 29 | Brain | Central orchestration engine | Live |

*(The PARIKA Console is intentionally not listed above -- it is an
Interface, not a Core component; see the Appendix following §29.)*
