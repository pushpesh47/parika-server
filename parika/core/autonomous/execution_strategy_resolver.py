"""
PARIKA Autonomous Execution - Execution Strategy Resolver

The authority for converting an implementation decision into an executable strategy.
This component bridges ImplementationResolver and Dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.authorization import (
    AutonomousAuthorizationBoundary,
    AutonomousAuthorizationRequest,
)
from parika.core.autonomous.budget import BudgetEnforcer, BudgetCheckResult
from parika.core.autonomous.execution_strategy import (
    ExecutionBackend,
    ExecutionStrategy,
    FallbackPolicy,
    RuntimeType,
)
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.implementation_registry.implementation_resolver import (
    ImplementationResolver,
    ImplementationResolution,
)
from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyResolutionResult:
    """Result of strategy resolution."""
    strategy: ExecutionStrategy
    fallback_strategies: tuple[ExecutionStrategy, ...]
    is_fallback: bool = False
    fallback_reason: str | None = None


class ExecutionStrategyResolver:
    """
    Resolves execution strategy from implementation decision.
    
    Single responsibility: Map ImplementationResolution -> ExecutionStrategy
    by considering task constraints, agent context, policy, budget, and runtime availability.
    
    Does NOT select implementations - that's ImplementationResolver's job.
    Does NOT dispatch execution - that's Dispatcher's job.
    """

    def __init__(
        self,
        *,
        implementation_resolver: ImplementationResolver,
        capability_registry: CapabilityRegistry,
        runtime_registry: RuntimeRegistry,
        authorization_boundary: AutonomousAuthorizationBoundary,
        budget_enforcer: BudgetEnforcer,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._implementation_resolver = implementation_resolver
        self._capability_registry = capability_registry
        self._runtime_registry = runtime_registry
        self._authorization_boundary = authorization_boundary
        self._budget_enforcer = budget_enforcer
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def resolve_strategy(
        self,
        *,
        implementation_resolution: ImplementationResolution,
        task_id: str,
        mission_id: str,
        agent_id: str | None,
        agent_profile_id: str | None,
        task_metadata: MappingProxyType[str, Any],
        step_index: int = 0,
        total_steps: int = 1,
        previous_results: MappingProxyType[str, Any] | None = None,
    ) -> StrategyResolutionResult:
        """
        Resolve a complete ExecutionStrategy from an ImplementationResolution.
        
        This is the single point where implementation -> strategy mapping occurs.
        """
        impl = implementation_resolution.implementation
        capability_id = implementation_resolution.request.capability_id
        
        # 1. Determine execution backend from implementation
        backend = self._map_implementation_to_backend(impl)
        
        # 2. Determine required environment from implementation
        required_env = self._map_implementation_to_environment(impl)
        
        # 3. Get fallback implementations
        fallback_impls = implementation_resolution.selection_result.fallback_candidates
        
        # 4. Build fallback strategies
        fallback_strategies = self._build_fallback_strategies(
            fallback_impls=fallback_impls,
            capability_id=capability_id,
            task_metadata=task_metadata,
            step_index=step_index,
            total_steps=total_steps,
        )
        
        # 5. Build primary strategy
        strategy = ExecutionStrategy(
            implementation_id=impl.id,
            implementation_version=impl.version,
            implementation_source=impl.source.value,
            capability_id=capability_id,
            backend=backend,
            required_environment=required_env,
            fallback_chain=tuple(f.id for f in fallback_impls),
            step_index=step_index,
            total_steps=total_steps,
            metadata=MappingProxyType({
                "task_id": task_id,
                "mission_id": mission_id,
                "agent_id": agent_id or "system",
                "agent_profile_id": agent_profile_id or "default",
            }),
        )
        
        return StrategyResolutionResult(
            strategy=strategy,
            fallback_strategies=fallback_strategies,
        )

    def validate_environment(self, strategy: ExecutionStrategy) -> bool:
        """
        Validate that the required execution environment is available.
        
        Returns True if available, False if fallback should be attempted.
        """
        return self._runtime_registry.is_available(strategy.required_environment)

    def try_fallback(
        self,
        failed_strategy: ExecutionStrategy,
        failure_class: str,
        task_metadata: MappingProxyType[str, Any],
    ) -> StrategyResolutionResult | None:
        """
        Attempt to resolve a fallback strategy after a failure.
        
        Args:
            failed_strategy: The strategy that failed
            failure_class: Type of failure ("selection_failure", "environment_unavailable", etc.)
            task_metadata: Task metadata for fallback resolution
            
        Returns:
            New StrategyResolutionResult with next fallback, or None if exhausted
        """
        # Check if automatic fallback is allowed for this failure class
        capability_def = self._capability_registry.get(failed_strategy.capability_id)
        fallback_policy = FallbackPolicy()
        if capability_def and hasattr(capability_def, 'fallback_policy'):
            fallback_policy = capability_def.fallback_policy
        
        if not fallback_policy.is_auto_fallback_allowed(failure_class):
            self._logger.info(
                "Automatic fallback not allowed for failure class '%s' on capability '%s'",
                failure_class, failed_strategy.capability_id
            )
            return None
        
        # Get fallback implementations from the failed strategy's chain
        fallback_impl_ids = failed_strategy.fallback_chain
        if not fallback_impl_ids:
            return None
        
        # Get the next fallback implementation
        next_fallback_id = fallback_impl_ids[0]
        # Note: We'd need to look up the actual implementation from the registry
        # For now, return None to indicate no fallback available
        # In full implementation, this would reconstruct the strategy
        
        self._logger.info(
            "Attempting fallback for capability '%s' after '%s' failure",
            failed_strategy.capability_id, failure_class
        )
        
        return None

    def _map_implementation_to_backend(self, impl: Any) -> ExecutionBackend:
        """Map implementation to execution backend based on source and runtime_type."""
        # Import here to avoid circular dependency
        from parika.core.autonomous.execution_strategy import ExecutionBackend
        from parika.core.implementation_registry.implementation import ImplementationSource
        from parika.core.capability_registry.capability_category import CapabilityCategory
        
        # Map by source first (most specific)
        if impl.source == ImplementationSource.HERMES:
            return ExecutionBackend.HERMES
        elif impl.source == ImplementationSource.REMOTE:
            return ExecutionBackend.REMOTE
        
        # For native/community/custom, map by runtime_type
        runtime_type = impl.metadata.runtime_type
        if runtime_type == "hermes":
            return ExecutionBackend.HERMES
        elif runtime_type == "remote":
            return ExecutionBackend.REMOTE
        elif runtime_type == "container":
            return ExecutionBackend.REMOTE  # Future: container backend
        else:
            # Default to native execution - determine TOOL vs PROVIDER
            # This requires capability definition to know category
            capability_def = self._capability_registry.get(impl.capability_id)
            if capability_def:
                # Check if it's a tool capability
                if capability_def.category == CapabilityCategory.TOOL:
                    return ExecutionBackend.TOOL
                # Non-TOOL native capabilities (LLM, VISION, etc.) use PROVIDER
                return ExecutionBackend.PROVIDER
            return ExecutionBackend.TOOL

    def _map_implementation_to_environment(self, impl: Any) -> RuntimeType:
        """Map implementation to required execution environment."""
        from parika.core.autonomous.execution_strategy import RuntimeType
        
        runtime_type = impl.metadata.runtime_type
        
        # Direct mapping
        try:
            return RuntimeType(runtime_type)
        except ValueError:
            # Fallback for unknown types
            return RuntimeType.NATIVE

    def _build_fallback_strategies(
        self,
        fallback_impls: tuple[Any, ...],
        capability_id: str,
        task_metadata: MappingProxyType[str, Any],
        step_index: int,
        total_steps: int,
    ) -> tuple[ExecutionStrategy, ...]:
        """Build fallback strategies from fallback implementations."""
        if not fallback_impls:
            return ()
        
        fallback_strategies = []
        for fallback_impl in fallback_impls:
            backend = self._map_implementation_to_backend(fallback_impl)
            required_env = self._map_implementation_to_environment(fallback_impl)
            
            strategy = ExecutionStrategy(
                implementation_id=fallback_impl.id,
                implementation_version=fallback_impl.version,
                implementation_source=fallback_impl.source.value,
                capability_id=capability_id,
                backend=backend,
                required_environment=required_env,
                fallback_chain=tuple(f.id for f in fallback_impls if f.id != fallback_impl.id),
                step_index=step_index,
                total_steps=total_steps,
            )
            fallback_strategies.append(strategy)
        
        return tuple(fallback_strategies)