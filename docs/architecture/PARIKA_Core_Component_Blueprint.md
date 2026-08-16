# PARIKA Core Component Blueprint

**Project:** PARIKA\
**Version:** 1.0\
**Status:** Frozen

------------------------------------------------------------------------

# Purpose

This document defines the standard blueprint that every PARIKA Core
component must follow.

It does **not** describe the architecture of PARIKA or coding
conventions.

Instead, it defines the anatomy, responsibilities, lifecycle, and
implementation boundaries of every Core component.

The goal is to ensure every Core component is consistent, maintainable,
and extensible.

------------------------------------------------------------------------

# Core Philosophy

Every Core component should:

-   Have one clear responsibility.
-   Expose one well-defined public entry point.
-   Minimize dependencies.
-   Be independently testable.
-   Be replaceable without affecting unrelated components.

------------------------------------------------------------------------

# Design Principles

Every Core component should satisfy:

-   High Cohesion
-   Low Coupling
-   Single Responsibility
-   Explicit Dependencies
-   Stable Public API
-   Predictable Lifecycle

------------------------------------------------------------------------

# Standard Package Layout

``` text
component/
│
├── __init__.py
├── component.py
├── exceptions.py        (optional)
├── constants.py         (optional)
├── types.py             (optional)
└── internal/            (optional)
```

Only create optional files when they serve an immediate purpose.

Never create empty files or speculative structure.

------------------------------------------------------------------------

# Public Entry Point

Every component exposes exactly one primary public class.

Examples:

-   Configuration
-   EventBus
-   Logging
-   ServiceContainer
-   ProviderManager

The package should expose only what other components need.

------------------------------------------------------------------------

# Responsibilities

Each component owns exactly one responsibility.

A component should have one primary reason to change.

If responsibilities begin diverging, split the implementation instead of
expanding the component indefinitely.

Publishing a component's own operational progress through the
existing, unmodified `EventBus` (`ProgressReporter`/`ProgressEvent`,
`parika/core/utilities/progress.py`) is a legitimate expression of a
component's single responsibility, not a second responsibility --
see Brain's `brain.execution.*` tree (Phase 3.5b,
`docs/architecture/Core_Component_Responsibilities.md` §29) for the
canonical pattern: an optional `event_bus` dependency used solely to
report the component's own work, never to subscribe to or react to
other components' events.

------------------------------------------------------------------------

# Public API

Public APIs should be:

-   Small
-   Explicit
-   Stable
-   Well documented

Expose behavior, not internal state.

------------------------------------------------------------------------

# Internal State

Internal state should:

-   Remain private
-   Be initialized in the constructor
-   Maintain valid object invariants
-   Avoid unnecessary mutability

------------------------------------------------------------------------

# Dependencies

Allowed:

-   Python Standard Library
-   Approved third-party libraries
-   PARIKA Core components through their public APIs

Forbidden:

-   Circular dependencies
-   Direct Module ↔ Module communication
-   Direct Provider ↔ Provider communication
-   Hidden global state

------------------------------------------------------------------------

# Lifecycle

A Core component progresses through:

1.  Construction
2.  Initialization
3.  Active operation
4.  Optional reload
5.  Graceful shutdown

Lifecycle behavior should be explicit.

------------------------------------------------------------------------

# Error Handling

Every component should define dedicated exception types when
appropriate.

Never expose implementation-specific exceptions as part of the public
API.

------------------------------------------------------------------------

# Configuration

Components receive configuration through the Configuration component.

Components must never modify global configuration.

------------------------------------------------------------------------

# Logging

Components never write directly to stdout.

Runtime diagnostics belong to the Logging component.

------------------------------------------------------------------------

# Thread Safety

Assume future concurrency.

Avoid shared mutable state.

Protect shared resources where necessary.

------------------------------------------------------------------------

# Testing

Every component includes tests covering:

-   Normal operation
-   Invalid input
-   Failure scenarios
-   Regression cases

See
[`../guides/Testing.md`](../guides/Testing.md)
for the full test-writing conventions and layout; this section only
states what every component's coverage must include.

------------------------------------------------------------------------

# Performance

Prioritize correctness first.

Optimize only after profiling demonstrates a need.

Avoid premature optimization.

------------------------------------------------------------------------

# Evolution Rules

A component may evolve by:

-   Adding new behavior within its responsibility.
-   Splitting internal implementation files.

A component must **not** evolve by taking on unrelated responsibilities.

If a new responsibility emerges, create a new Core component or move the
functionality to a Module, Provider, Tool, or Policy.

------------------------------------------------------------------------

# Decision Criteria

Before changing a Core component, ask:

-   Does this belong in the Core?
-   Does it violate the Single Responsibility Principle?
-   Can it be implemented as a Module instead?
-   Does it preserve the frozen architecture?
-   Will it remain understandable years from now?

If the answer is uncertain, perform an architecture review before
implementation.

------------------------------------------------------------------------

# Final Principle

Every Core component should embody one simple rule:

> **One responsibility. One public entry point. One owner. One reason to
> change.**

This blueprint applies to every present and future Core component in
PARIKA.
