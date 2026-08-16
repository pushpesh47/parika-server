"""
PARIKA Coding Agent - Registry

Selects the appropriate `CodingAgent` implementation for a
`CodingTaskDescriptor`, without any change to `CodingAgentToolDriver`,
`ToolManager`, `Planner`, or `Brain` required to add a new agent. See
docs/development/Module_Guide.md Addendum A
section A.3.2.
"""

from __future__ import annotations

from collections.abc import Sequence

from .agent import CodingAgent, CodingTaskDescriptor
from .exceptions import UnknownCodingAgentError


class CodingAgentRegistry:
    """
    Holds every registered `CodingAgent`, in registration order.
    """

    def __init__(self, agents: Sequence[CodingAgent]) -> None:
        if not agents:
            raise ValueError("CodingAgentRegistry requires at least one agent.")

        self._agents: tuple[CodingAgent, ...] = tuple(agents)

    def get(self, agent_id: str) -> CodingAgent:
        """
        Look up a specific agent by id -- used when
        `CodingTaskDescriptor.requested_agent_id` is set, bypassing
        heuristic selection entirely.

        Raises:
            UnknownCodingAgentError:
                If no registered agent has this id.
        """

        for agent in self._agents:
            if agent.id == agent_id:
                return agent

        raise UnknownCodingAgentError(
            f"No registered CodingAgent has id '{agent_id}'."
        )

    def select(self, task: CodingTaskDescriptor) -> CodingAgent:
        """
        Select the best-matching agent for `task`.

        An explicit `task.requested_agent_id` always wins (user
        preference/configuration). Otherwise, the first registered
        agent whose `supports()` returns `True` is selected --
        deterministic, registration-order tie-breaking, the same
        discipline `Planner`'s own dependency ordering and model
        selection already use elsewhere in this codebase. The last
        registered agent is expected to be an unconditional fallback
        (e.g. `StandardCodingAgent`).
        """

        if task.requested_agent_id is not None:
            return self.get(task.requested_agent_id)

        for agent in self._agents:
            if agent.supports(task):
                return agent

        return self._agents[-1]

    def all(self) -> tuple[CodingAgent, ...]:
        return self._agents
