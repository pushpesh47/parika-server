# PARIKA Development Documentation

## Purpose

This section contains implementation guidance for extending PARIKA without changing its architecture.

## Canonical Guides

- [Capability_Guide.md](Capability_Guide.md) for capability definitions and registration.
- [Module_Guide.md](Module_Guide.md) for module development.
- [Tool_Guide.md](Tool_Guide.md) for tool development.
- [Model_Selection_Guide.md](Model_Selection_Guide.md) for planner/model selection extension.
- [Requirement_Inference_Guide.md](Requirement_Inference_Guide.md) for adding a new capability so AI Context Engineering discovers it automatically.
- [Provider_Tool_Calling_Guide.md](Provider_Tool_Calling_Guide.md) for provider-side tool calling behavior.
- [Integration_Checklist.md](Integration_Checklist.md) for integration validation.

## When to Use Each Guide

- Use capability and module guides when adding new features.
- Use the tool guide when implementing deterministic capabilities.
- Use the model selection guide when changing planning behavior, and the capability-discovery guide when adding a new capability domain.
- Use the provider tool calling guide when diagnosing provider-side tool invocation issues.
