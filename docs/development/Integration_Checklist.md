
# PARIKA Integration Checklist

**Status:** Authoritative integration checklist for extending PARIKA.

> This document replaces **PARIKA_Integration_Guide.md**. It is a quick implementation checklist. Detailed implementation belongs in the Module, Tool, and Capability Guides.

---

# Before You Start

- Read the Architecture Specification.
- Follow Core Coding Standards.
- Respect Core Component Responsibilities.
- Do not bypass the frozen architecture.

---

# 1. Integrating a Module

Checklist

- Create the module package.
- Implement ModuleDriver.
- Create ModuleManifest.
- Register during application startup.
- Load through ModuleManager.
- Register Capabilities.
- Register Tools and/or Providers.
- Register optional health checks.
- Subscribe to required events.
- Unregister everything during shutdown.
- Write unit tests.

Reference:

- Module_Guide.md

---

# 2. Integrating a Tool

Checklist

- Create Tool package.
- Create Tool descriptor.
- Implement ToolDriver.
- Register from ModuleDriver.start().
- Return ToolResponse.
- Use dependency injection.
- Write unit tests using fake I/O.
- If the Tool implements more than one Capability, register one Tool
  per Capability (see Tool_Guide.md §21) - never dispatch on an
  internal "operation" argument inside a single Tool.

Reference:

- Tool_Guide.md

---

# 3. Integrating a Capability

Checklist

- Define CapabilityDefinition.
- Choose the correct category.
- Register from Module startup.
- Register implementation together with Capability.
- Verify resolution.
- Test enable/disable behavior.

Reference:

- Capability_Guide.md

---

# 4. Integrating a Provider

Checklist

- Implement `ProviderDriver` (`parika/core/provider_manager/driver.py`):
  exactly three abstract methods -- `discover_models() -> frozenset[ProviderModel]`,
  `check_health() -> ProviderHealth`, and
  `execute(model: ProviderModel, request: ProviderRequest) -> ProviderResponse`.
- Create Provider descriptor.
- Register Provider.
- Discover models.
- Refresh health.
- Verify Planner can select it.
- Test execution.

**Reference implementation:** `parika/providers/ollama/` is the one
`ProviderDriver` implementation that ships today
(`OllamaProviderDriver`) -- it is the concrete template for a new
Provider, the same role the Web Search Tool plays for `Tool_Guide.md`.
Note in particular that model selection stays entirely inside Planner
(`Model_Selection_Guide.md`): a new Provider never needs to implement
any selection logic itself, only report `ProviderModel.metadata` keys
that existing or new `ScoringRule`s can read generically.

---

# 5. Integrating a Knowledge Engine

Checklist

- Implement KnowledgeEngine.
- Register engine.
- Verify indexing.
- Verify searching.
- Test engine failures.

---

# 6. Integrating a Knowledge Source

Checklist

- Create KnowledgeSource.
- Register source.
- Index source.
- Update status.
- Remove source.
- Verify search behavior.

---

# 7. Integrating a Workflow

Checklist

- Define Workflow.
- Register Workflow.
- Verify lifecycle.
- Test execution support before depending on it.

---

# 8. Integrating Policies

Checklist

- Create PolicyRule.
- Attach rule to Goals.
- Verify evaluation.
- Test conflict resolution.

---

# 9. Integrating Scheduler Jobs

Checklist

- Schedule jobs during startup.
- Cancel jobs during shutdown.
- Test recurring jobs.
- Test failure handling.
- Be aware that `Scheduler.cancel()` raises `JobAlreadyFinishedError`
  for a job that is already `JobStatus.RUNNING` (its callback has
  already started executing on the Timer's background thread) rather
  than marking it `CANCELLED` — a running callback cannot be
  interrupted. Callers (including `shutdown()`, which already catches
  `SchedulerError` broadly) must treat "already running" the same way
  as "already finished": as too late to cancel, not as an error to
  surface to an end user.
- When testing a scheduled job's cancellation against a specific
  in-flight state (e.g. `RUNNING`), synchronize with a
  `threading.Event` the callback sets itself rather than a
  `time.sleep()` guess — see `docs/guides/Testing.md` section 3,
  "Testing concurrency-sensitive components deterministically."

---

# 10. Integrating Event Subscribers

Checklist

- Subscribe during startup.
- Unsubscribe during shutdown.
- Verify payloads.
- Test event handling.

---

# 11. Exposing a Capability Through the API Layer

The Server Platform (`parika/server/`, `parika/api/` — see
`docs/guides/Running.md` section 12) never requires an API redesign to
reach a capability that already exists: every registered capability
is already reachable via the generic
`POST /api/v1/capabilities/{capability_id}/execute` fallback endpoint
the moment it is registered with `CapabilityRegistry` — no extra work
is required for a new capability to be reachable at all.

Checklist for giving a capability its own **dedicated**, ergonomic
endpoint (preferred over the generic fallback once one exists):

- Add a Pydantic request/response schema pair to `parika/api/schemas/`
  (never imported by Core).
- Add an internal `ApiRequest` dataclass to `parika/api/requests.py`
  for the operation (not necessarily one per HTTP endpoint).
- Add a `Route` binding in `parika/api/router_bindings.py`, dispatched
  through the existing `Router` Core component — never a direct
  Core-manager call from a route function.
- Add the orchestration/translation-only handler to
  `parika/api/handlers/` — it may call an existing Core manager/driver
  method and compose already-existing read-only calls, but must never
  implement a new decision, validation rule, or state transition that
  does not already exist inside some Core component.
- Add the `APIRouter` to `parika/api/routers/` and mount it in
  `parika/api/routers/__init__.py`'s `build_v1_router()`.
- Never rename an existing endpoint's path, never remove an existing
  request field, and make every new field optional/backward
  compatible — a breaking change requires `/api/v2`, not a change to
  `/api/v1`.
- Add router tests under `tests/api/routers/` (`fastapi.testclient
  .TestClient`, no real socket) and, if the capability streams,
  WebSocket tests under `tests/api/ws/`.
- Regenerate `docs/api/PARIKA_API_Reference.html`:
  `python scripts/generate_api_docs.py`.

---

# Final Integration Checklist

Before merging:

- Architecture respected
- Dependency Injection used
- No Core modifications
- Registration implemented
- Cleanup implemented
- Logging added
- Tests written
- Documentation updated

---

# Related Documentation

- architecture/PARIKA_Architecture_Specification_v1.0.md
- architecture/Core_Component_Responsibilities.md
- architecture/PARIKA_Core_Coding_Standards.md
- architecture/PARIKA_Decision_Flow.md
- development/Module_Guide.md
- development/Tool_Guide.md
- development/Capability_Guide.md
- guides/Running.md
- guides/Testing.md
- api/PARIKA_API_Reference.html (generated — see guides/Running.md §12.8)
