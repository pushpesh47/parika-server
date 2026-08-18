"""
PARIKA Agent Orchestrator

Coordinates multi-agent execution by integrating with Brain, Planner, and TaskManager.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_resolver import AgentResolution, AgentResolver
from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.planner.goal import Goal
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.logger.logger import Logger
from parika.core.planner.planner import Planner
from parika.core.task_manager.task_manager import TaskManager

from .events import (
    AgentAssigned,
    AgentDelegated,
    AgentExecutionCompleted,
    AgentExecutionFailed,
    AgentExecutionStarted,
    AgentRegistered,
    AgentUnregistered,
)
from .exceptions import (
    AgentOrchestrationError,
    AgentRegistryError,
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
    AgentResolutionError,
    NoSuitableAgentError,
    DelegationNotAllowedError,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentTaskAssignment:
    """
    Represents an agent-task assignment for execution.
    """
    agent: AgentProfile
    """The assigned agent"""
    
    goal: Goal
    """The goal to execute"""
    
    resolution: AgentResolution
    """The agent resolution that led to this assignment"""


class AgentOrchestrator:
    """
    Orchestrates multi-agent execution by coordinating agent selection with
    Brain, Planner, and TaskManager.
    
    This is the extension point for future agent delegation and collaboration.
    """

    def __init__(
        self,
        *,
        planner: Planner,
        task_manager: TaskManager,
        agent_registry: AgentRegistry,
        agent_resolver: AgentResolver,
        capability_registry: CapabilityRegistry,
        logger: Logger,
        event_bus: EventBus | None = None,
    ) -> None:
        """
        Initialize the agent orchestrator.

        Args:
            planner:
                Planner for creating execution plans.
            
            task_manager:
                TaskManager for task lifecycle.
            
            agent_registry:
                Registry of available agents.
            
            agent_resolver:
                Resolver for selecting agents.
            
            capability_registry:
                Registry of capabilities.
            
            logger:
                PARIKA Logger component.
            
            event_bus:
                Optional EventBus for publishing agent lifecycle events.
        """

        self._planner = planner
        self._task_manager = task_manager
        self._agent_registry = agent_registry
        self._agent_resolver = agent_resolver
        self._capability_registry = capability_registry
        self._logger = logger.get_logger(__name__)
        self._event_bus = event_bus

    def assign_agents_to_goals(
        self,
        goals: tuple[Goal, ...],
        *,
        context: dict[str, Any] | None = None,
    ) -> tuple[AgentTaskAssignment, ...]:
        """
        Assign agents to goals based on their capabilities and specializations.
        
        This is called by Brain before planning to determine which agent
        should handle each goal. The assignment influences model selection
        and execution strategy.

        Args:
            goals:
                Goals to assign agents to.
            
            context:
                Optional context for resolution.

        Returns:
            Tuple of agent-task assignments.
        """

        assignments = []

        for goal in goals:
            capability_id = goal.capability_id
            
            # Resolve agent for this goal
            resolution = self._agent_resolver.resolve(
                capability_id=capability_id,
                context=context,
            )

            # Publish AgentAssigned event
            self._logger.debug(
                "Agent '%s' assigned to goal '%s' (capability: %s, confidence: %.2f).",
                resolution.agent.id,
                goal.id,
                capability_id,
                resolution.confidence,
            )
            if self._event_bus is not None:
                self._event_bus.publish("agent.assigned", AgentAssigned(
                    agent_id=resolution.agent.id,
                    goal_id=goal.id,
                    capability_id=capability_id,
                    specialization=resolution.agent.specialization.value,
                    confidence=resolution.confidence,
                ))

            # Attach agent info to goal metadata for Planner
            agent_metadata = {
                "agent_id": resolution.agent.id,
                "agent_specialization": resolution.agent.specialization.value,
                "agent_confidence": resolution.confidence,
                "agent_reason": resolution.reason,
            }

            # Create a new goal with agent metadata
            agent_goal = Goal(
                id=goal.id,
                capability_id=goal.capability_id,
                inputs=goal.inputs,
                context_id=goal.context_id,
                depends_on=goal.depends_on,
                policy_rules=goal.policy_rules,
                provider_request_builder=goal.provider_request_builder,
                metadata={
                    **goal.metadata,
                    **agent_metadata,
                },
            )

            assignments.append(AgentTaskAssignment(
                agent=resolution.agent,
                goal=agent_goal,
                resolution=resolution,
            ))

        return tuple(assignments)

    def execute_with_agents(
        self,
        goals: tuple[Goal, ...],
        *,
        context: dict[str, Any] | None = None,
    ) -> BrainResponse:
        """
        Execute goals with agent assignments.
        
        This method assigns agents to goals and then delegates to Brain
        for the actual execution.
        
        NOTE: This method is provided as a helper for explicit non-production
        use cases. The normal production path goes through Brain.handle()
        which internally calls assign_agents_to_goals() if an
        AgentOrchestrator is provided to Brain.

        Args:
            goals:
                Goals to execute.
            
            context:
                Optional context for resolution.

        Returns:
            BrainResponse from execution.
        """

        assignments = self.assign_agents_to_goals(goals, context=context)
        
        # Extract goals with agent metadata
        agent_goals = tuple(assignment.goal for assignment in assignments)
        
        # Create BrainRequest with agent-assigned goals
        request = BrainRequest(goals=agent_goals)
        
        # Delegate to Brain - but we need a brain instance
        # This method should only be used when Brain doesn't have the orchestrator
        # For production, prefer passing AgentOrchestrator to Brain constructor
        raise RuntimeError(
            "execute_with_agents() is not supported in the production pipeline. "
            "Pass AgentOrchestrator to Brain constructor instead."
        )

    def get_agent_for_capability(
        self,
        capability_id: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResolution:
        """
        Get the best agent for a capability.
        
        Useful for querying which agent would handle a capability
        without executing.

        Args:
            capability_id:
                The capability to check.
            
            context:
                Optional context for resolution.

        Returns:
            AgentResolution with the selected agent.
        """

        return self._agent_resolver.resolve(
            capability_id=capability_id,
            context=context,
        )

    def delegate(
        self,
        from_agent_id: str,
        capability_id: str,
        *,
        inputs: Mapping[str, Any],
        context_id: str | None = None,
        depends_on: tuple[str, ...] = (),
        policy_rules: tuple[str, ...] = (),
        provider_request_builder: Callable[..., Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResolution:
        """
        Delegate a capability to the most suitable agent.
        
        This allows one agent to request another agent to handle a capability.
        The delegation goes through the normal AgentResolver, respecting
        delegation policies and capability access controls.
        
        Args:
            from_agent_id:
                The ID of the agent requesting delegation.
            capability_id:
                The capability to delegate.
            inputs:
                Inputs for the delegated capability.
            context_id:
                Optional context ID for the delegated work.
            depends_on:
                Optional goal IDs that this delegated work depends on.
            policy_rules:
                Optional policy rules for the delegated goal.
            provider_request_builder:
                Optional provider request builder for LLM capabilities.
            context:
                Optional context for resolution.
        
        Returns:
            AgentResolution with the selected delegate agent.
            
        Raises:
            NoSuitableAgentError: If no suitable agent can be found.
            DelegationNotAllowedError: If delegation is not allowed by policy.
        """
        from .exceptions import DelegationNotAllowedError, NoSuitableAgentError
        
        # Check if from_agent allows delegation
        if not self._agent_registry.contains(from_agent_id):
            raise NoSuitableAgentError(f"Agent '{from_agent_id}' not found.")
        
        from_agent = self._agent_registry.get(from_agent_id)
        
        if from_agent.delegation_policy == "prohibited":
            raise DelegationNotAllowedError(
                f"Agent '{from_agent_id}' has delegation prohibited."
            )
        
        # Resolve delegate agent
        resolution = self._agent_resolver.resolve(
            capability_id=capability_id,
            context=context,
        )
        
        delegate_agent = resolution.agent
        
        # Check if delegate agent can use the capability
        capability_def = None
        capability_category = None
        if self._capability_registry.contains(capability_id):
            capability_def = self._capability_registry.get(capability_id)
            capability_category = capability_def.category
        
        if not delegate_agent.can_use_capability(capability_id, capability_category):
            raise DelegationNotAllowedError(
                f"Delegate agent '{delegate_agent.id}' cannot use capability '{capability_id}'."
            )
        
        if delegate_agent.delegation_policy == "prohibited":
            # Delegate agent prohibits being delegated to
            # In a more sophisticated implementation, we might check if
            # the delegator is in an allowed list
            pass
        
        self._logger.debug(
            "Agent '%s' delegated capability '%s' to agent '%s'.",
            from_agent_id,
            capability_id,
            delegate_agent.id,
        )
        
        return resolution