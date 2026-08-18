# PARIKA Architecture Specification v1.0

**Project:** PARIKA\
**Full Name:** Personal Adaptive Responsive Intelligence Kernel
Assistant

**Status:** Constitution / Authoritative Architecture Reference

**Version:** 1.0

**Architecture State:** Frozen (changes require architecture review)

------------------------------------------------------------------------

# Purpose of this document

This document defines the long-term architectural constitution of
PARIKA.

It answers **what PARIKA is**, **what it is not**, **how it is
structured**, and **the rules that govern every future architectural
decision**.

Coding standards, implementation details, and project conventions are
intentionally kept in a separate document.

------------------------------------------------------------------------

# Vision

PARIKA (Personal Adaptive Responsive Intelligence Kernel Assistant) aims to become a lifelong personal intelligence kernel that works alongside its user as a trusted digital companion.

Unlike traditional chatbots or AI applications, PARIKA is designed to be the central intelligence layer that understands the user's work, projects, knowledge, preferences, goals, and digital environment. It intelligently coordinates artificial intelligence models, software tools, automation, memory, knowledge, workspaces, system resources, and user-defined policies to help users think, learn, create, automate, and solve problems more effectively.

PARIKA is designed to deliver a seamless, intuitive, and consistent user experience across all supported interfaces, including desktop, web, command-line, voice, and future interaction methods. Its user interface should remain clean, responsive, accessible, and distraction-free, allowing users to interact naturally while keeping complex orchestration hidden behind a simple and elegant experience. Regardless of how users choose to interact with PARIKA, they should feel as though they are working with one unified, intelligent system rather than a collection of separate tools.

Built on a local-first, modular, capability-driven, event-driven, and provider-agnostic architecture, PARIKA is designed to evolve with future technologies without requiring fundamental architectural changes. It prioritizes user privacy, transparency, extensibility, resource-aware execution, workspace awareness, and long-term maintainability while remaining independent of any specific AI provider, language model, or operating system.

The long-term vision of PARIKA is to become a unified personal intelligence platform that continuously grows with its user, seamlessly integrates emerging technologies, adapts to changing workflows, and serves as a reliable digital partner for work, learning, creativity, software development, research, automation, and everyday computing for many years to come.



------------------------------------------------------------------------

# Mission

PARIKA's mission is to provide a single intelligent platform that can seamlessly coordinate AI providers, language models, software tools, automation systems, memory, workspaces, and knowledge sources through a stable orchestration kernel.

Instead of replacing existing software, PARIKA enhances it by acting as an intelligent coordinator that automatically selects the best capabilities, manages resources efficiently, remembers relevant context, respects user-defined policies, and continuously adapts to changing technologies while remaining independent of any specific AI vendor or model

------------------------------------------------------------------------

# Aim

The aim of PARIKA is to build an AI platform that can:

1. Understand the user's work and projects.
2. Assist with software development and technical problem solving.
3. Manage memory and long-term knowledge.
4. Coordinate multiple AI providers and models automatically.
5. Use local resources whenever possible.
6. Access the internet only when necessary or permitted.
7. Automate repetitive workflows.
8. Support voice, vision, coding, research, and future capabilities.
9. Continuously improve through modular expansion rather than architectural redesign.
10. Remain maintainable, scalable, and future-proof for the next decade and beyond.

------------------------------------------------------------------------

# What is PARIKA? (Simple Explanation)

Imagine you have a very smart personal assistant.

This assistant:
1. remembers what you are working on,
2. knows which AI is best for each job,
3. can use your computer,
4. can organize your files,
5. can search your documents,
6. can help you write code,
7. can automate repetitive tasks,
8. can answer questions,
9. can learn your preferences,
10. and can keep improving over time.

Now imagine that instead of being connected to only one AI, it can work with many different AI models and automatically choose the best one for every task.

It also works mostly on your own computer, keeping your information private and under your control.

That is PARIKA.

It is not an operating system.

It is not just a chatbot.

It is the intelligence layer that sits on top of your computer and coordinates AI, tools, memory, knowledge, and automation so everything works together as one personal assistant.

You can think of PARIKA as the brain of your digital workspace. Just as a human brain coordinates different parts of the body, PARIKA coordinates different AI models, software tools, and services to help you work more efficiently and intelligently.

## Architectural Boundary: Server, the PARIKA Console, and External Clients

PARIKA Server is a separate application from any *external* client application. The server contains the Brain, Memory, Knowledge, Providers, Modules, Tools, Workflows, Intelligence, Planning, and Reasoning components. External client applications are presentation layers only. Each external platform has its own client application, such as Desktop, Web, Android, iOS, TV, or Smartwatch. Every external client communicates with the PARIKA Server through APIs. The server performs all reasoning; external clients simply send requests and display responses.

PARIKA has one further, permanently separate concept that is *not* an external client (Phase 3.5b): the **PARIKA Console** (`parika/console/`). The Console is bundled with the server and communicates with PARIKA Core directly, in-process -- exactly like every other Core-adjacent component, not through `/api/v1`. It has unrestricted administrative capabilities, is not limited by the REST or WebSocket API shape, and is not subject to client authentication or rate limiting. It is intended for administration, debugging, development, diagnostics, recovery, and server management, and is PARIKA's primary administration interface. See section 6 ("Dependency Rules") for its exact dependency boundaries, and `docs/architecture/Core_Component_Responsibilities.md` ("PARIKA Console" section) for its full responsibilities.

Example:

```text
Android Client  ->  PARIKA Server API  ->  Brain      (external client)
Desktop Client  ->  PARIKA Server API  ->  Brain      (external client)
Web Client      ->  PARIKA Server API  ->  Brain      (external client)
PARIKA Console  ->  Brain                              (in-process, no API)
```

# 1. Final Architecture

``` text
PARIKA/
│
├── Core/
│   ├── Brain
│   ├── Planner
│   ├── Router
│   ├── WorkflowEngine
│   ├── TaskManager
│   ├── Scheduler
│   ├── LifecycleManager
│   ├── StateManager
│   ├── HealthManager
│   ├── MetricsManager
│   ├── EventBus
│   ├── ContextManager
│   ├── MemoryManager
│   ├── KnowledgeManager
│   ├── CapabilityRegistry
│   ├── CapabilityResolver
│   ├── CapabilityExecutor
│   ├── ProviderManager
│   ├── ModuleManager
│   ├── ToolManager
│   ├── ResourceManager
│   ├── PolicyEngine
│   ├── PermissionManager
│   ├── ServiceContainer
│   ├── UpdateManager
│   ├── Configuration
│   ├── Logging
│   ├── Security
│   └── Utilities
│
├── Providers/
├── Tools/
├── Modules/
├── Interfaces/       (shared Interface infrastructure: session, commands, formatting)
├── Console/          (the native, in-process PARIKA Console -- see "Architectural
│                      Boundary" above; not an external client)
├── Policies/
├── Data/
├── Config/
├── Plugins/
├── API/              (REST/WebSocket surface for external clients only)
├── Tests/
├── Docs/
└── Logs/
```
---------------------------------------------------------------------------



# 2. Goals

-   Local-first execution
-   Capability-driven routing
-   Provider independence
-   Model independence
-   Event-driven architecture
-   Dynamic policy system
-   Workspace awareness
-   Resource-aware execution
-   Modular expansion
-   Long-term maintainability
-   Stable Core with replaceable components

------------------------------------------------------------------------

# 3. Non-Goals

PARIKA is **not**:

-   An operating system
-   A monolithic chatbot
-   Bound to any AI vendor
-   Hardcoded around any model
-   A collection of scripts
-   A microservice platform
-   Designed around cloud-first execution

------------------------------------------------------------------------

# 4. Core Design Principles

1.  Local First
2.  Capability Driven
3.  Provider Agnostic
4.  Module Isolation
5.  Dynamic Policies
6.  Event Driven
7.  Resource Aware
8.  Self Benchmarking
9.  Workspace Awareness
10. Replace Everything

------------------------------------------------------------------------

# 5. Frozen Core

The Core consists of the following architectural components:

-   Brain
-   Planner
-   Router
-   WorkflowEngine
-   TaskManager
-   Scheduler
-   LifecycleManager
-   StateManager
-   HealthManager
-   MetricsManager
-   EventBus
-   ContextManager
-   MemoryManager
-   KnowledgeManager
-   CapabilityRegistry
-   CapabilityResolver
-   ProviderManager
-   ModuleManager
-   ToolManager
-   ResourceManager
-   PolicyEngine
-   PermissionManager
-   ServiceContainer
-   UpdateManager
-   Configuration
-   Logging
-   Security
-   Utilities

These components form the stable kernel of PARIKA.

------------------------------------------------------------------------

# 5.1. Core Implementation Order

1.  Configuration
2.  ServiceContainer
3.  Logging
4.  EventBus
5.  Utilities
6.  Security

7.  StateManager
8.  ResourceManager
9.  CapabilityRegistry
10. CapabilityResolver
11. ContextManager
12. MemoryManager
13. KnowledgeManager

14. ProviderManager
15. ToolManager
16. ModuleManager

17. WorkflowEngine
18. CapabilityExecutor
19. TaskManager
20. Scheduler

21. LifecycleManager
22. HealthManager
23. MetricsManager

24. PolicyEngine
25. PermissionManager
26. UpdateManager

27. Router
28. Planner
29. Brain

------------------------------------------------------------------------

# 5.2. Capability Catalog (Retrieval Layer, additive)

`parika/core/capability_catalog/` is a read-only retrieval/index layer
built on top of `CapabilityRegistry`, consumed only by AI Context
Engineering (`parika/interfaces/ai_context/capability_context.py`),
before Brain/Planner ever run. It is an additive package, not a member
of the Frozen Core list in §5 -- it introduces no new execution
concept and changes nothing about how `CapabilityRegistry`,
`CapabilityResolver`, `ToolManager`, `ModuleManager`, or
`ProviderManager` behave. See `docs/architecture/
Request_Understanding.md` §4.6 for its full pipeline and rationale
(narrowing the router-advertised roster as the registered capability
count grows, without changing the execution architecture after the
router).

------------------------------------------------------------------------


# 6. Dependency Rules

Interfaces

↓

Core

↓

Modules / Providers / Tools

Rules:

-   Interfaces communicate only with Core.
-   The PARIKA Console (`parika/console/`) is an Interface in this
    dependency sense -- it communicates only with Core, in-process,
    and Core never depends on it. It is not "an external client";
    it never crosses an API boundary.
-   The API layer (`parika/api/`) never depends on the Console
    (`parika/console/`) or on any concrete Interface, and the Console
    never depends on the API layer -- they are permanently separate,
    each constructing its own `ParikaRuntime`.
-   Core never depends on Modules, Providers or Tools.
-   Modules communicate only through Core services and EventBus.
-   Providers never communicate directly with each other.
-   Tools never communicate directly with Modules.
-   Policy decisions belong exclusively to the Policy Engine.

------------------------------------------------------------------------

# 7. Capability System

Modules request capabilities instead of specific providers or models.

Selection pipeline:

User → Brain → AgentOrchestrator → Planner → CapabilityResolver → ResourceManager →
PolicyEngine → ProviderManager → Best Provider → Best Model

------------------------------------------------------------------------

# 7. Capability System

Modules request capabilities instead of specific providers or models.

Selection pipeline:

User → Brain → AgentOrchestrator → Planner → CapabilityResolver → ResourceManager →
PolicyEngine → ProviderManager → Best Provider → Best Model

------------------------------------------------------------------------

## 7.1 Multi-Agent Execution

PARIKA supports multi-agent execution where a single user request can
produce multiple Goals, each assigned to a different specialized agent.
The multi-agent architecture is built on the existing execution
pipeline without duplicating systems:

**Architecture:**

User Request
    ↓
Brain
    ↓
AgentOrchestrator
    ↓
Planner
    ↓
ExecutionPlan
    ↓
Dependency-Aware Concurrent Execution
    ↓
TaskManager
    ↓
CapabilityExecutor
    ↓
Tools / Providers

**Key Principles:**

- **Single Pipeline:** Brain remains the single execution entry point.
  `AgentOrchestrator` is called from `Brain.handle()` before planning,
  not as a separate pipeline.
- **Agent Assignment:** `AgentOrchestrator.assign_agents_to_goals()`
  assigns agents to Goals based on capability, specialization, and
  policy. Agent metadata (`agent_id`, `agent_specialization`,
  `agent_confidence`, `agent_reason`) is attached to Goal metadata
  for downstream consumption by Planner and TaskManager.
- **Dependency-Aware Concurrency:** Independent Goals execute
  concurrently (up to `[concurrency] max_concurrent_goals`). Dependent
  Goals wait for their dependencies. Failed dependencies cause
  dependent Goals to be skipped. Unrelated Goals continue independently.
- **Agent Identity Propagation:** Agent metadata (`agent_id`,
  `agent_specialization`) propagates through Goal.metadata →
  PlanStep.execution_request.metadata → TaskRequest.metadata →
  Task.metadata. No `Task.agent_id` field is required.
- **Agent Policies:** Agents have `preferred_capabilities`,
  `allowed_capabilities`, `prohibited_capabilities`. `AgentResolver`
  enforces these during assignment. Prohibited capabilities are never
  executed by an agent.
- **Delegation:** `AgentOrchestrator.delegate()` allows one agent to
  request another agent's specialization. Delegation goes through
  `AgentResolver`, respects capability policies, and uses the existing
  Planner/TaskManager pipeline.
- **Model/Provider Preferences:** Agent preferences
  (`preferred_models`, `preferred_providers`, `model_constraints`) are
  stored in `ExecutionRequirements.metadata["agent_preferences"]` for
  future integration with the existing model selection framework.
- **Voice Compatibility:** Voice input follows the same pipeline:
  speech-to-text → Brain → AgentOrchestrator → Planner → ...
- **Context UI Compatibility:** Semantic capability context is
  preserved. Agent identity does not replace semantic context.
- **No Duplicate Systems:** The multi-agent architecture extends the
  existing Brain/Planner/TaskManager/CapabilityExecutor pipeline.
  There is no AgentManager, AgentPlanner, AgentTaskManager, or
  AgentScheduler.

------------------------------------------------------------------------

# 8. Policy System

Policies define behavior instead of code.

Examples:

-   Local-only AI
-   Internet restrictions
-   Quiet hours
-   Workspace rules
-   Battery-aware routing
-   Production safeguards

------------------------------------------------------------------------

# 9. Configuration Architecture

Configuration is layered.

Default Values

↓

Installation Configuration

↓

Workspace Configuration

↓

Environment Variables

↓

Runtime Overrides

Higher layers override lower layers.

------------------------------------------------------------------------

# 10. Event Model

Components communicate through the EventBus.

Avoid direct dependencies whenever possible.

Events should be descriptive, versionable, and stable.

## 10.1 EventBus Channel Catalog (illustrative, not exhaustive)

Two families of channels exist, and both are documented per-component
in `docs/architecture/Core_Component_Responsibilities.md`:

- **Domain/lifecycle events** -- one typed dataclass per publishing
  component, e.g. `router.dispatch.started/completed/failed`,
  `task.created/started/completed/failed`, `tool.executed`/
  `tool.execution_failed`, `capability.execution.started/completed/
  failed`, `capability.registered/unregistered/enabled/disabled`,
  `provider.registered/models_discovered/health_updated`,
  `module.*`, `policy.evaluated`, `memory.*`, `knowledge.*`,
  `permission.*`, `health.*`, `lifecycle.*`, `update.*`, `workflow.*`,
  `scheduler.*`.
- **Generic execution-progress events** (Phase 3.5b; see
  `parika/core/utilities/progress.py`'s `ProgressEvent`/
  `ProgressReporter`) -- every publisher's specific channel
  (`f"{source_id}.{stage}"`) plus a fixed, generic channel
  (`progress.started`/`progress.progress`/`progress.completed`/
  `progress.failed`) that any subscriber (e.g. the PARIKA Console)
  subscribes to once, for the process lifetime, to observe every
  present and future publisher's progress with zero code change.
  Current publishers: `brain.execution` (root, per `Brain.handle()`
  call, with `brain.planning` and `brain.execute_goal` children --
  the sole owner of execution-progress reporting so every present and
  future caller of `Brain.handle()` gets it for free), `memory.search`
  (`MemoryManager.search()`), `knowledge.search`
  (`KnowledgeManager.search()`), and any Tool/Module's own
  `ProgressReporter` usage (e.g. `filesystem.search`, `coding.index`).

`capability.execution.started/completed/failed` additionally carry an
optional `task_id` (Phase 3.5b), correlating one capability execution
to its owning `TaskManager` `Task.id` and to its own Started/
Completed/Failed counterpart -- `None` when execution was requested
without one.

------------------------------------------------------------------------

# 11. Workspace Model

Workspaces isolate:

-   Configuration
-   Memory
-   Knowledge
-   Policies
-   Modules
-   Data

The Core remains workspace-agnostic.

------------------------------------------------------------------------

# 12. Provider SDK

Providers implement a common contract.

Typical capabilities include:

-   Model discovery
-   Capability reporting
-   Health status
-   Streaming
-   Tool calling
-   Vision
-   Embeddings
-   Image/video generation

Providers are interchangeable.

Two providers ship in this repository: Ollama (`parika/providers/ollama/`
— chat, tool calling, vision) and ComfyUI (`parika/providers/comfyui/`
— image generation/editing, text/image-to-video generation) — see
`PARIKA_Decision_Flow.md` §8.1 for how ComfyUI satisfies the same
`ProviderDriver` contract as Ollama.

------------------------------------------------------------------------

# 13. Module SDK

Every module should expose:

-   Metadata
-   Declared capabilities
-   Event subscriptions
-   Configuration
-   Lifecycle hooks
-   Permissions
-   Health checks

Modules never communicate directly with other modules.

------------------------------------------------------------------------

# 14. Extension Philosophy

Future functionality should be added through:

-   Modules
-   Providers
-   Tools
-   Policies

Avoid expanding the Core unless a capability genuinely belongs there.

------------------------------------------------------------------------

# 15. Stability Guarantee

The Core is intended to remain stable.

Breaking architectural changes require explicit architecture review.

------------------------------------------------------------------------

# 16. Architecture Decision Records

Major architectural decisions should be documented as ADRs under:

docs/architecture/adr/

Each ADR should include:

-   Context
-   Decision
-   Alternatives
-   Consequences

------------------------------------------------------------------------

# 17. Roadmap

Phase 1 -- Project Skeleton

Phase 2 -- Core Infrastructure

Phase 3 -- SDKs

Phase 4 -- Managers

Phase 5 -- Capability & Policy Systems

Phase 6 -- Resource & Health Systems

Phase 7 -- Memory & Knowledge

Phase 8 -- Workflow

Phase 9 -- Providers

Phase 10 -- Interfaces

Phase 11 -- Modules

Phase 12 -- UI & Dashboard

Phase 13 -- Testing & Optimization

Phase 14 -- Packaging & Distribution

------------------------------------------------------------------------

# 18. Final Principle

Architecture should be earned, not anticipated.

Prefer simplicity over cleverness.

Prefer stable APIs over rapid expansion.

Protect the Core.

------------------------------------------------------------------------

# Version History

## v1.0

Initial frozen architecture defining:

-   Core architecture
-   Dependency rules
-   Capability-driven routing
-   Policy-driven behavior
-   Configuration architecture
-   Extension philosophy
-   Long-term stability principles
