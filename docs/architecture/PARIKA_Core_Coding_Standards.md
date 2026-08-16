# PARIKA Core Coding Standards

**Version:** 1.0

**Status:** Frozen

------------------------------------------------------------------------

# Purpose

This document defines the mandatory engineering standards for all PARIKA
Core components.

The Architecture Specification defines **what** PARIKA is.

This document defines **how** PARIKA is implemented.

Unless an architecture review explicitly approves an exception, these
standards must be followed by every Core component.

------------------------------------------------------------------------

# Engineering Philosophy

Every implementation should prioritize:

1.  Simplicity
2.  Readability
3.  Maintainability
4.  Stability
5.  Extensibility

Optimize for code that remains understandable years later.

------------------------------------------------------------------------

# Core Principles

The Core must always remain:

-   Local First
-   Provider Agnostic
-   Capability Driven
-   Event Driven
-   Resource Aware
-   Workspace Aware

------------------------------------------------------------------------

# Package Structure

Every Core component owns its own package.

Example:

``` text
parika/core/
    configuration/
    logging/
    security/
    event_bus/
```

Never mix unrelated responsibilities inside a package.

------------------------------------------------------------------------

# Naming Rules

## Packages

Use `snake_case`.

## Files

Use `snake_case`.

## Classes

Use `PascalCase`.

## Functions

Use `snake_case`.

## Variables

Use descriptive names. Avoid abbreviations.

------------------------------------------------------------------------

# Import Rules

1.  Python Standard Library
2.  Third-party libraries
3.  PARIKA packages

Separate each group with one blank line.

Never use wildcard imports.

------------------------------------------------------------------------

## Code Organization

## Import Ordering

All Python source files **must** organize imports in the following order to ensure consistency, readability, and maintainability across the PARIKA codebase.

### Import Order

```text
1. __future__ imports

2. Python standard library

3. Third-party libraries (if any)

4. Absolute imports (parika.*)

5. Relative imports (.)
```

### Rules

- `from __future__` imports **must always** appear first.
- Separate each import group with **one blank line**.
- Imports within each group should be **alphabetically ordered** whenever practical.
- Do not mix imports from different groups.
- Use **absolute imports** (`parika.*`) when importing modules from other packages within the PARIKA project.
- Use **relative imports** only when importing modules from the same package.
- Remove unused imports before committing code.
- Avoid wildcard imports (`from module import *`).

### Example

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from pydantic import BaseModel

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .provider import Provider
from .provider_model import ProviderModel
```

### Rationale

This import ordering provides a consistent structure throughout the codebase by:

- Clearly separating Python built-in modules from project-specific modules.
- Making third-party dependencies immediately identifiable.
- Improving readability and reducing merge conflicts.
- Following PEP 8 recommendations while adopting a project-specific convention for PARIKA.
- Providing a predictable import structure across all Core components.

------------------------------------------------------------------------
# Type Hints

Mandatory for:

-   Functions
-   Methods
-   Parameters
-   Return values
-   Public attributes

Prefer explicit types.

Avoid `Any` unless there is no practical alternative.

------------------------------------------------------------------------

# Docstrings

Public classes require docstrings.

Public methods require docstrings.

Docstrings explain intent rather than implementation.

------------------------------------------------------------------------

# Public API

Expose the smallest possible public API.

Everything else remains private.

Private members begin with `_`.

------------------------------------------------------------------------

# Dependency Rules

The full dependency direction rules (Interfaces -> Core ->
Modules/Providers/Tools) are defined once in
[`PARIKA_Architecture_Specification_v1.0.md`](PARIKA_Architecture_Specification_v1.0.md)
§6 and are not repeated here. The coding-level consequence of that rule:

Use EventBus, ServiceContainer and explicit dependency injection.

Never introduce circular dependencies.

------------------------------------------------------------------------

# Dependency Injection

Prefer constructor injection.

Avoid hidden globals.

------------------------------------------------------------------------

# State Management

Prefer immutable data.

Keep mutable state localized.

Avoid global mutable state.

------------------------------------------------------------------------

# Configuration

Configuration is read-only outside the Configuration component.

------------------------------------------------------------------------

# Logging

Never use `print()` inside Core.

------------------------------------------------------------------------

# Error Handling

Never raise generic `Exception`.

Create dedicated exception classes.

Differentiate configuration, policy, provider and resource errors.

------------------------------------------------------------------------

# Thread Safety

Assume future concurrency.

Avoid shared mutable state.

------------------------------------------------------------------------

# Performance

Correctness before optimization.

Prefer readability over cleverness.

------------------------------------------------------------------------

# Security

Never use:

-   eval()
-   exec()
-   pickle

inside the Core without explicit architectural approval.

------------------------------------------------------------------------

# Standard Library First

Prefer the Python Standard Library before introducing dependencies.

------------------------------------------------------------------------

# File Size Guidelines

Preferred: under 300 lines.

Maximum: 500 lines.

Split responsibilities before files become difficult to maintain.

------------------------------------------------------------------------

# Single Responsibility

Each class should have one primary responsibility.

------------------------------------------------------------------------

# Testing

Every public Core component should eventually have unit tests covering:

-   Normal behaviour
-   Edge cases
-   Failure scenarios
-   Regression prevention

------------------------------------------------------------------------

# Documentation

Document purpose, responsibilities and limitations.

------------------------------------------------------------------------

# Backward Compatibility

Public APIs are stable.

Breaking changes require architecture review.

------------------------------------------------------------------------

# Code Review Checklist

-   Architecture preserved
-   Type hints present
-   Documentation updated
-   Tests added
-   No circular dependencies
-   Minimal dependencies

------------------------------------------------------------------------

# Final Principle

Same final principle as
[`PARIKA_Architecture_Specification_v1.0.md`](PARIKA_Architecture_Specification_v1.0.md)
§18, applied at the code level: prefer simple, stable, maintainable
solutions over clever or anticipatory ones.
