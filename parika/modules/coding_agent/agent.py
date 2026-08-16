"""
PARIKA Coding Agent - Agent Protocol

Internal-only pluggable extensibility point (per the refinement's own
scope statement: "this is ONLY an internal extensibility mechanism").
The public `coding.execute_task` Capability stays stable; internally,
`CodingAgentToolDriver` dispatches to whichever registered
`CodingAgent` implementation `CodingAgentRegistry` selects. The fifth
instance, in this codebase, of the "Protocol + registry + default
implementations" shape already used by `ScoringRule`,
`KnowledgeEngine`, `LanguageAnalyzer`, and `ProjectDetector`. See
docs/development/Module_Guide.md Addendum A
section A.3.2.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from parika.core.brain.goal_result import GoalResult


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingTaskDescriptor:
    """
    Everything a `CodingAgent` implementation needs to decide whether
    it applies, and to execute -- built once by `CodingAgentToolDriver`
    from the incoming `ToolRequest`.
    """

    instruction: str
    workspace_root: Path
    requested_agent_id: str | None = None
    max_depth: int = 3
    depth: int = 0
    task_id: str | None = None
    allowed_write_roots: tuple[Path, ...] = ()
    require_test_run: bool = False
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingAgentResult:
    """
    The outcome of one `CodingAgent.execute()` call.
    """

    summary: str
    goal_results: tuple[GoalResult, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )

    @property
    def succeeded(self) -> bool:
        return all(result.succeeded for result in self.goal_results)


@runtime_checkable
class CodingAgent(Protocol):
    """
    One implementation per specialized agent behavior (standard, fast,
    deep analysis, security review, documentation, refactoring, ...).
    """

    @property
    def id(self) -> str: ...

    def supports(self, task: CodingTaskDescriptor) -> bool:
        """
        Must be cheap and deterministic -- never a Provider call just
        to decide applicability (see
        docs/development/Module_Guide.md
        Addendum A section A.7).
        """
        ...

    def execute(self, task: CodingTaskDescriptor) -> CodingAgentResult: ...
