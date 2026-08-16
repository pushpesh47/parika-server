# PARIKA Documentation

## Purpose

This directory is the long-term documentation hub for PARIKA. It is organized to help both humans and AI assistants understand the project quickly without reading duplicate or stale material. Every concept has exactly one canonical, authoritative document; every other document links to it instead of repeating it.

## What Is PARIKA?

PARIKA is a local-first, personal AI assistant kernel. **PARIKA Server is a
separate application from any client application** — the server contains
the Brain, Memory, Knowledge, Providers, Modules, Tools, Workflows,
Intelligence, Planning, and Reasoning; clients (Desktop, Web, Android, iOS,
TV, Smartwatch) are presentation layers only and talk to the server over an
API. This boundary is defined once, authoritatively, in
[architecture/PARIKA_Architecture_Specification_v1.0.md](architecture/PARIKA_Architecture_Specification_v1.0.md)
("Architectural Boundary: Server and Clients") — do not restate it
elsewhere; link to it instead.

## Where Do I...?

Quick answers for a new contributor or AI assistant — each links to the one place that question is authoritatively answered, never a summary repeated here:

| Question | Answer |
|---|---|
| What is PARIKA, and what is it not? | [architecture/PARIKA_Architecture_Specification_v1.0.md](architecture/PARIKA_Architecture_Specification_v1.0.md) |
| How does a request travel through PARIKA, end to end? | [architecture/PARIKA_Decision_Flow.md](architecture/PARIKA_Decision_Flow.md) §1 |
| Which component owns what, and why? | [architecture/Core_Component_Responsibilities.md](architecture/Core_Component_Responsibilities.md) |
| How should a new Core component be structured? | [architecture/PARIKA_Core_Component_Blueprint.md](architecture/PARIKA_Core_Component_Blueprint.md) |
| What coding rules apply before I write any code? | [architecture/PARIKA_Core_Coding_Standards.md](architecture/PARIKA_Core_Coding_Standards.md) |
| Where do I implement a new Tool? | [development/Tool_Guide.md](development/Tool_Guide.md) |
| Where do I implement a new Module? | [development/Module_Guide.md](development/Module_Guide.md) |
| Where do I implement a new Provider? | [development/Integration_Checklist.md](development/Integration_Checklist.md) §4, using `parika/providers/ollama/` as the one shipped reference implementation of the `ProviderDriver` interface |
| Where do I register a new Capability? | [development/Capability_Guide.md](development/Capability_Guide.md) |
| Where should genuinely new functionality go — a new Module, or a Core change? | [architecture/PARIKA_Architecture_Specification_v1.0.md](architecture/PARIKA_Architecture_Specification_v1.0.md) §14 ("Extension Philosophy") |
| How do I run PARIKA locally? | [guides/Running.md](guides/Running.md) |
| How do I run or write tests? | [guides/Testing.md](guides/Testing.md) |

## Documentation Map

| Folder | Contents | Canonical for |
|---|---|---|
| [`architecture/`](architecture/) | Frozen system model, component responsibilities (including the current, implemented state of Memory/Knowledge/Experience/Context/Session), coding standards, runtime decision flow, and the design of each major subsystem (Model Selection, Provider Tool Calling, AI Context Engineering / Capability Discovery). | What PARIKA is and how it is architected. |
| [`architecture/adr/`](architecture/adr/) | Architecture Decision Records — historical, one per significant decision, recording context, decision, and rejected alternatives. | Why a decision was made this way. |
| [`development/`](development/) | "How do I build/extend X" guides for Capabilities, Modules, Tools, Model Selection, adding a new Capability for AI Context Engineering, and Provider Tool Calling. | How to implement or extend PARIKA. |
| [`guides/`](guides/) | Operational guides: installing, configuring, running, and testing PARIKA. | How to run and test PARIKA. |
| [`examples/`](examples/) | End-to-end, concrete walkthroughs of request execution, model selection, and tool-calling hardening. | What actually happens, in a real example. |

## Recommended Reading Order

1. Read the architecture overview in [architecture/PARIKA_Architecture_Specification_v1.0.md](architecture/PARIKA_Architecture_Specification_v1.0.md).
2. Read the execution flow in [architecture/PARIKA_Decision_Flow.md](architecture/PARIKA_Decision_Flow.md).
3. Review component responsibilities in [architecture/Core_Component_Responsibilities.md](architecture/Core_Component_Responsibilities.md) and the component template in [architecture/PARIKA_Core_Component_Blueprint.md](architecture/PARIKA_Core_Component_Blueprint.md).
4. Read [architecture/PARIKA_Core_Coding_Standards.md](architecture/PARIKA_Core_Coding_Standards.md) before writing any code.
5. Use the development guides in [development/README.md](development/README.md) when implementing or extending PARIKA.
6. Use [guides/Running.md](guides/Running.md) and [guides/Testing.md](guides/Testing.md) for day-to-day work.
7. Read [examples/Request_Execution_Examples.md](examples/Request_Execution_Examples.md) for concrete, verified walkthroughs of the flow described in step 2.

## Documentation Conventions

- Current architecture documents are the authoritative reference. Every concept (Capability, Tool, Module, Provider, Workflow, Planner, Brain, Memory) is named consistently everywhere; if you need to introduce a new term, check it isn't already covered by an existing one first.
- Design proposals are merged into their canonical document once implemented and verified against the code, rather than kept as a separate, permanent "history" record — see the ADR entries below for *why* a decision was made a particular way, and the canonical document itself for *what* is actually implemented today.
- ADRs (`architecture/adr/`) remain the place for architecture decisions and rejected alternatives; they link to, and do not duplicate, the canonical design document for the feature.
- New work should add or update the canonical document for the topic rather than creating a duplicate guide. If you find duplicated content while working, replace the copy with a link to the canonical source.
