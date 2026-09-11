"""
PARIKA Implementation Resolver

Resolves capability requests to specific implementations using
hard gates + fitness scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_request import CapabilityRequest
from parika.core.capability_resolver.capability_resolution import CapabilityResolution
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.skill_system.skill_registry import SkillRegistry

from .implementation import CapabilityImplementation
from .implementation_registry import ImplementationRegistry, ImplementationFilter


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionCandidate:
    """A candidate implementation for selection."""
    implementation: CapabilityImplementation
    hard_gate_passed: bool
    gate_failures: tuple[str, ...]
    fitness_score: float
    score_breakdown: MappingProxyType[str, float]


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionResult:
    """Result of implementation selection."""
    selected: CapabilityImplementation | None
    candidates: tuple[SelectionCandidate, ...]
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class ImplementationResolution:
    """Resolution of a capability to an implementation."""
    request: CapabilityRequest
    capability_resolution: CapabilityResolution
    implementation: CapabilityImplementation
    selection_result: SelectionResult
    resolved_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ImplementationResolver:
    """
    Resolves capability requests to specific implementations.

    Selection process:
    1. Find all implementations for the capability
    2. Apply hard gates (security, policy, permission, compatibility, resources)
    3. Score remaining candidates by fitness factors
    4. Select best candidate
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        capability_resolver: Any,  # CapabilityResolver - avoid circular import
        implementation_registry: ImplementationRegistry,
        skill_registry: SkillRegistry,
        policy_engine: PolicyEngine,
        permission_manager: PermissionManager,
        workspace_permissions: WorkspacePermissionManager,
        resource_manager: ResourceManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._capability_registry = capability_registry
        self._capability_resolver = capability_resolver
        self._implementation_registry = implementation_registry
        self._skill_registry = skill_registry
        self._policy_engine = policy_engine
        self._permission_manager = permission_manager
        self._workspace_permissions = workspace_permissions
        self._resource_manager = resource_manager
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        # Scoring weights (configurable)
        self._weights = {
            "experience": 0.30,
            "reliability": 0.25,
            "latency": 0.15,
            "cost": 0.10,
            "resource_efficiency": 0.10,
            "runtime_preference": 0.10,
        }

    def resolve(
        self,
        request: CapabilityRequest,
        *,
        context: MappingProxyType[str, Any] | None = None,
        agent_id: str | None = None,
        agent_profile_id: str | None = None,
        mission_id: str | None = None,
        task_id: str | None = None,
        allowed_runtimes: tuple[str, ...] = (),
        preferred_runtime: str | None = None,
    ) -> ImplementationResolution:
        """
        Resolve a capability request to an implementation.

        Args:
            request: Capability request
            context: Execution context
            agent_id: Agent making the request
            agent_profile_id: Agent profile ID
            mission_id: Mission ID
            task_id: Task ID
            allowed_runtimes: Allowed runtime types
            preferred_runtime: Preferred runtime type

        Returns:
            ImplementationResolution with selected implementation
        """
        # First resolve the capability
        capability_resolution = self._capability_resolver.resolve(request)

        # Find candidate implementations
        candidates = self._implementation_registry.get_implementations_for_capability(
            request.capability_id,
            status=None,  # Include all for gating
        )

        if not candidates:
            raise ValueError(f"No implementations found for capability '{request.capability_id}'")

        # Apply hard gates
        gated_candidates = self._apply_hard_gates(
            candidates,
            context=context or MappingProxyType({}),
            agent_id=agent_id,
            agent_profile_id=agent_profile_id,
            mission_id=mission_id,
            task_id=task_id,
            allowed_runtimes=allowed_runtimes,
        )

        # Filter to only passed candidates
        passed = [c for c in gated_candidates if c.hard_gate_passed]

        if not passed:
            # No candidates passed hard gates - provide detailed failure info
            all_failures = []
            for c in gated_candidates:
                all_failures.extend(c.gate_failures)
            raise ValueError(
                f"No implementations passed hard gates for capability '{request.capability_id}': "
                f"{'; '.join(set(all_failures))}"
            )

        # Score candidates
        scored = self._score_candidates(
            passed,
            context=context or MappingProxyType({}),
            preferred_runtime=preferred_runtime,
        )

        # Select best
        best = max(scored, key=lambda c: c.fitness_score)

        selection_result = SelectionResult(
            selected=best.implementation,
            candidates=tuple(scored),
            reason=f"Selected {best.implementation.id} with score {best.fitness_score:.3f}",
        )

        resolution = ImplementationResolution(
            request=request,
            capability_resolution=capability_resolution,
            implementation=best.implementation,
            selection_result=selection_result,
        )

        self._event_bus.publish("implementation.resolved", {
            "capability_id": request.capability_id,
            "selected_implementation": best.implementation.id,
            "source": best.implementation.source.value,
            "score": best.fitness_score,
            "candidates_evaluated": len(scored),
        })

        self._logger.info(
            "Resolved capability '%s' to implementation '%s' (score: %.3f)",
            request.capability_id,
            best.implementation.id,
            best.fitness_score,
        )

        return resolution

    def _apply_hard_gates(
        self,
        candidates: list[CapabilityImplementation],
        *,
        context: MappingProxyType[str, Any],
        agent_id: str | None,
        agent_profile_id: str | None,
        mission_id: str | None,
        task_id: str | None,
        allowed_runtimes: tuple[str, ...],
    ) -> list[SelectionCandidate]:
        """Apply hard gates to filter candidates."""
        gated = []

        for impl in candidates:
            failures = []

            # Gate 1: Implementation status
            if impl.status != "active":
                failures.append(f"Implementation not active (status: {impl.status.value})")

            # Gate 2: Security status
            if impl.security_status == "blocked":
                failures.append("Implementation blocked by security")

            # Gate 3: Runtime availability
            if allowed_runtimes and impl.metadata.runtime_type not in allowed_runtimes:
                failures.append(f"Runtime '{impl.metadata.runtime_type}' not allowed")

            # Gate 4: Tool availability
            for tool_id in impl.metadata.tool_ids:
                if not self._tool_manager_available(tool_id):
                    failures.append(f"Required tool '{tool_id}' not available")

            # Gate 5: Skill availability
            for skill_id in impl.metadata.skill_ids:
                skill = self._skill_registry.get_skill(skill_id)
                if not skill:
                    failures.append(f"Required skill '{skill_id}' not found")
                elif not skill.is_activatable():
                    failures.append(f"Required skill '{skill_id}' not activatable (trust: {skill.trust_state.value}, security: {skill.security_status.value})")

            # Gate 6: Policy evaluation
            if not self._check_policy(impl, context, agent_id, agent_profile_id, mission_id, task_id):
                failures.append("Policy evaluation denied")

            # Gate 7: Permission check
            if not self._check_permissions(impl, agent_id, mission_id, task_id):
                failures.append("Permission check failed")

            # Gate 8: Resource requirements
            if not self._check_resources(impl, context):
                failures.append("Insufficient resources")

            # Gate 9: Environment compatibility
            if not self._check_environment(impl, context):
                failures.append("Environment requirements not met")

            gate_passed = len(failures) == 0

            gated.append(SelectionCandidate(
                implementation=impl,
                hard_gate_passed=gate_passed,
                gate_failures=tuple(failures),
                fitness_score=0.0,
                score_breakdown=MappingProxyType({}),
            ))

        return gated

    def _tool_manager_available(self, tool_id: str) -> bool:
        """Check if tool is available (placeholder - would check actual tool manager)."""
        # This would integrate with actual ToolManager
        return True

    def _check_policy(
        self,
        impl: CapabilityImplementation,
        context: MappingProxyType[str, Any],
        agent_id: str | None,
        agent_profile_id: str | None,
        mission_id: str | None,
        task_id: str | None,
    ) -> bool:
        """Check policy for implementation."""
        from parika.core.policy_engine.request import PolicyEvaluationRequest
        from parika.core.policy_engine.policy_effect import PolicyEffect

        # Build policy context
        policy_context = dict(context)
        policy_context.update({
            "capability_id": impl.capability_id,
            "implementation_id": impl.id,
            "implementation_source": impl.source.value,
            "runtime_type": impl.metadata.runtime_type,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "mission_id": mission_id,
            "task_id": task_id,
        })

        # Evaluate policies (would need actual policy rules)
        # For now, assume allowed unless explicitly denied
        return True

    def _check_permissions(
        self,
        impl: CapabilityImplementation,
        agent_id: str | None,
        mission_id: str | None,
        task_id: str | None,
    ) -> bool:
        """Check permissions for implementation."""
        # Check tool permissions
        for tool_id in impl.metadata.tool_ids:
            if agent_id:
                decision = self._permission_manager.check(agent_id, f"tool:{tool_id}")
                if not decision.authorized:
                    return False

        # Check workspace permissions for filesystem/shell tools
        # This would be more granular in practice
        return True

    def _check_resources(
        self,
        impl: CapabilityImplementation,
        context: MappingProxyType[str, Any],
    ) -> bool:
        """Check resource requirements."""
        # Get resource snapshot
        resource_snapshot = self._resource_manager.get_resource_snapshot()

        # Check CPU
        cpu_req = impl.metadata.resource_requirements.get("cpu_cores", 0)
        if cpu_req > 0:
            available_cpu = resource_snapshot.cpu.logical_core_count or 0
            if cpu_req > available_cpu:
                return False

        # Check memory
        mem_req = impl.metadata.resource_requirements.get("memory_mb", 0)
        if mem_req > 0:
            available_mem_mb = resource_snapshot.memory.available_bytes / (1024 * 1024)
            if mem_req > available_mem_mb * 0.8:  # 80% threshold
                return False

        return True

    def _check_environment(
        self,
        impl: CapabilityImplementation,
        context: MappingProxyType[str, Any],
    ) -> bool:
        """Check environment requirements."""
        env_req = impl.metadata.required_environment

        # Check required environment variables
        for var_name in env_req.get("required_env_vars", []):
            if var_name not in context and var_name not in env_req:
                return False

        # Check OS compatibility
        required_os = env_req.get("os")
        if required_os:
            import platform
            if platform.system().lower() != required_os.lower():
                return False

        return True

    def _score_candidates(
        self,
        candidates: list[SelectionCandidate],
        *,
        context: MappingProxyType[str, Any],
        preferred_runtime: str | None,
    ) -> list[SelectionCandidate]:
        """Score candidates by fitness factors."""
        scored = []

        for candidate in candidates:
            impl = candidate.implementation
            breakdown = {}

            # Experience score (historical success)
            exp_score = impl.experience_score
            breakdown["experience"] = exp_score

            # Reliability score
            rel_score = impl.reliability_score
            breakdown["reliability"] = rel_score

            # Latency score (inverted - lower is better)
            if impl.avg_latency_ms > 0:
                # Normalize: assume 1000ms is baseline, score = 1000/latency capped at 1
                lat_score = min(1.0, 1000.0 / impl.avg_latency_ms)
            else:
                lat_score = 0.5  # Unknown latency
            breakdown["latency"] = lat_score

            # Cost score (inverted - lower is better)
            if impl.avg_cost > 0:
                # Normalize: assume $0.01 is baseline
                cost_score = min(1.0, 0.01 / impl.avg_cost)
            else:
                cost_score = 0.5  # Unknown cost
            breakdown["cost"] = cost_score

            # Resource efficiency
            cpu_req = impl.metadata.resource_requirements.get("cpu_cores", 0)
            mem_req = impl.metadata.resource_requirements.get("memory_mb", 0)
            resource_score = 1.0
            if cpu_req > 0 or mem_req > 0:
                resource_score = 0.8  # Slight penalty for resource requirements
            breakdown["resource_efficiency"] = resource_score

            # Runtime preference
            runtime_score = 1.0
            if preferred_runtime and impl.metadata.runtime_type != preferred_runtime:
                runtime_score = 0.5
            breakdown["runtime_preference"] = runtime_score

            # Calculate weighted fitness score
            fitness = sum(
                breakdown[factor] * weight
                for factor, weight in self._weights.items()
            )

            scored.append(SelectionCandidate(
                implementation=impl,
                hard_gate_passed=True,
                gate_failures=(),
                fitness_score=fitness,
                score_breakdown=MappingProxyType(breakdown),
            ))

        return scored

    def select_fallback(
        self,
        failed_implementation_id: str,
        request: CapabilityRequest,
        *,
        context: MappingProxyType[str, Any] | None = None,
        agent_id: str | None = None,
        mission_id: str | None = None,
        task_id: str | None = None,
    ) -> ImplementationResolution | None:
        """
        Select a fallback implementation after a failure.

        Args:
            failed_implementation_id: The implementation that failed
            request: Original capability request
            context: Execution context
            agent_id: Agent ID
            mission_id: Mission ID
            task_id: Task ID

        Returns:
            New ImplementationResolution or None if no fallback available
        """
        # Get all implementations for this capability
        candidates = self._implementation_registry.get_implementations_for_capability(
            request.capability_id,
        )

        # Filter out the failed one
        candidates = [c for c in candidates if c.id != failed_implementation_id]

        if not candidates:
            return None

        # Apply hard gates again (excluding the failed one)
        gated = self._apply_hard_gates(
            candidates,
            context=context or MappingProxyType({}),
            agent_id=agent_id,
            mission_id=mission_id,
            task_id=task_id,
            allowed_runtimes=(),
        )

        passed = [c for c in gated if c.hard_gate_passed]
        if not passed:
            return None

        # Score and select best
        scored = self._score_candidates(
            passed,
            context=context or MappingProxyType({}),
            preferred_runtime=None,
        )

        best = max(scored, key=lambda c: c.fitness_score)

        selection_result = SelectionResult(
            selected=best.implementation,
            candidates=tuple(scored),
            reason=f"Fallback to {best.implementation.id} after {failed_implementation_id} failed",
        )

        return ImplementationResolution(
            request=request,
            capability_resolution=None,  # Would need to re-resolve
            implementation=best.implementation,
            selection_result=selection_result,
        )