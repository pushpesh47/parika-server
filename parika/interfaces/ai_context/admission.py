"""
PARIKA AI Context Engineering - Execution Mode Admission

Deterministic admission control for proposed execution mode.
Separates SEMANTIC classification (LLM) from OPERATIONAL admission (deterministic).
"""

from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from parika.interfaces.session import InterfaceSession

from parika.core.policy_engine.policy_effect import PolicyEffect
from parika.core.policy_engine.request import PolicyEvaluationRequest

from parika.core.brain.brain import Brain
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.planner.goal import Goal
from parika.interfaces.runtime import ParikaRuntime

from parika.core.autonomous.execution_mode import (
    AdmissionDecision,
    AdmissionState,
    ExecutionMode,
)


class ExecutionModeAdmission:
    """
    Deterministic admission control for proposed execution mode.
    
    Separates SEMANTIC classification (LLM) from OPERATIONAL admission (deterministic).
    """

    def __init__(
        self,
        *,
        runtime: ParikaRuntime,
        session: InterfaceSession,
    ) -> None:
        self._runtime = runtime
        self._session = session
        self._logger = logging.getLogger(__name__)

    def resolve(
        self,
        proposed_semantic_mode: ExecutionMode,
        confidence: Optional[float],
        reasons: tuple[str, ...],
        goals: tuple[Goal, ...],
    ) -> AdmissionDecision:
        """
        Resolve the final admission decision.
        
        If LLM proposed NORMAL → admit NORMAL (no further checks needed).
        If LLM proposed AUTONOMOUS → run admission checks.
        """
        # If LLM proposed NORMAL, admit NORMAL immediately
        if proposed_semantic_mode is ExecutionMode.NORMAL:
            return AdmissionDecision(
                proposed_semantic_mode=ExecutionMode.NORMAL,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.ADMITTED,
                reason="LLM proposed normal execution",
            )

        # LLM proposed AUTONOMOUS - run admission checks
        return self._admit_autonomous(proposed_semantic_mode, confidence, reasons, goals)

    def _admit_autonomous(
        self,
        proposed_semantic_mode: ExecutionMode,
        confidence: Optional[float],
        reasons: tuple[str, ...],
        goals: tuple[Goal, ...],
    ) -> AdmissionDecision:
        """Run autonomous admission checks."""
        
        # 1. Validate LLM output
        if confidence is None or confidence < 0.6:
            return AdmissionDecision(
                proposed_semantic_mode=proposed_semantic_mode,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.LOW_CONFIDENCE,
                reason=f"Low confidence: {confidence}",
            )

        if proposed_semantic_mode not in ExecutionMode:
            return AdmissionDecision(
                proposed_semantic_mode=proposed_semantic_mode,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.INVALID_PROPOSAL,
                reason="Invalid execution mode from LLM",
            )
        
        # 2. Check autonomous runtime availability
        if not self._runtime.autonomous_runtime or not self._runtime.autonomous_runtime.is_started:
            return AdmissionDecision(
                proposed_semantic_mode=proposed_semantic_mode,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.UNAVAILABLE_RUNTIME,
                reason="AutonomousRuntime not started",
            )
        
        # 3. Check config
        if not self._runtime.configuration.get("autonomous.enabled", True):
            return AdmissionDecision(
                proposed_semantic_mode=proposed_semantic_mode,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.CONFIG_DISABLED,
                reason="Autonomous execution disabled in configuration",
            )
        
        # 4. Policy admission
        policy_engine = self._runtime.policy_engine
        
        capability_ids = [g.capability_id for g in goals]
        
        context = {
            "is_autonomous": True,
            "capability_ids": capability_ids,
            "session_id": self._session.id,
        }
        
        # Use canonical PARIKA policy pattern: empty rules with ALLOW default
        # (following brain.py _get_recovery_capabilities and planner.py _enforce_policy)
        request = PolicyEvaluationRequest(
            context=context,
            rules=(),
            default_effect=PolicyEffect.ALLOW,
        )
        
        policy_decision = policy_engine.evaluate(request)
        if not policy_decision.is_allowed:
            return AdmissionDecision(
                proposed_semantic_mode=proposed_semantic_mode,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.DENIED_POLICY,
                reason=f"Policy denied: {policy_decision.reason}",
                policy_decision_id=policy_decision.matched_rule_id,
            )
        
        # 5. Permission admission
        perm_decision = self._check_autonomous_permissions(goals)
        if not perm_decision.authorized:
            return AdmissionDecision(
                proposed_semantic_mode=proposed_semantic_mode,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.DENIED_PERMISSIONS,
                reason=f"Permissions denied: {perm_decision.reason}",
                permission_details={"reason": perm_decision.reason},
            )
        
        # 6. Resource admission (coarse)
        resource_decision = self._check_autonomous_resources(goals)
        if not resource_decision.allowed:
            return AdmissionDecision(
                proposed_semantic_mode=proposed_semantic_mode,
                admitted_mode=ExecutionMode.NORMAL,
                admission_state=AdmissionState.DENIED_RESOURCES,
                reason=f"Resources insufficient: {resource_decision.reason}",
                resource_details={"reason": resource_decision.reason},
            )
        
        # ALL CHECKS PASSED
        return AdmissionDecision(
            proposed_semantic_mode=proposed_semantic_mode,
            admitted_mode=proposed_semantic_mode,
            admission_state=AdmissionState.ADMITTED,
            reason="Autonomous execution admitted",
        )

    def _check_autonomous_permissions(self, goals: tuple[Goal, ...]) -> Any:
        """Check if permissions allow autonomous execution for these goals."""
        permission_manager = self._runtime.permission_manager
        
        # Check autonomous:execute grant
        decision = permission_manager.check(
            subject_id="autonomous",
            operation="execute",
        )
        
        if not decision.authorized:
            return decision
        
        # Check workspace permissions for filesystem/shell capabilities
        workspace_capabilities = {
            "filesystem.read", "filesystem.write", "filesystem.list",
            "filesystem.delete", "filesystem.mkdir", "shell.execute",
        }
        
        for goal in goals:
            if goal.capability_id in workspace_capabilities:
                # Get workspace path from goal inputs
                workspace_path = goal.inputs.get("path")
                if workspace_path:
                    from pathlib import Path
                    ws_decision = self._runtime.workspace_permissions.check(
                        path=Path(workspace_path),
                        operation=self._map_capability_to_workspace_op(goal.capability_id),
                    )
                    if not ws_decision.authorized:
                        return ws_decision
        
        return decision

    def _map_capability_to_workspace_op(self, capability_id: str) -> Any:
        """Map capability to workspace operation."""
        from parika.core.permission_manager.workspace_operation import WorkspaceOperation
        
        if capability_id in ("filesystem.read", "filesystem.list"):
            return WorkspaceOperation.READ
        elif capability_id in ("filesystem.write", "filesystem.delete", "filesystem.mkdir"):
            return WorkspaceOperation.WRITE
        elif capability_id == "shell.execute":
            return WorkspaceOperation.EXECUTE
        return WorkspaceOperation.READ

    def _check_autonomous_resources(self, goals: tuple[Goal, ...]) -> Any:
        """Check if system resources can support autonomous execution."""
        from dataclasses import dataclass
        
        @dataclass
        class ResourceDecision:
            allowed: bool
            reason: str = ""
        
        # Coarse check: system CPU and memory
        snapshot = self._runtime.resource_manager.get_resource_snapshot()
        
        # Check configured limits
        config = self._runtime.configuration
        max_cpu = config.get("autonomous.max_cpu_percent", 90.0)
        max_memory = config.get("autonomous.max_memory_percent", 90.0)
        
        if snapshot.cpu.usage_percent > max_cpu:
            return ResourceDecision(
                allowed=False,
                reason=f"System CPU usage {snapshot.cpu.usage_percent}% exceeds limit {max_cpu}%",
            )
        
        if snapshot.memory.usage_percent > max_memory:
            return ResourceDecision(
                allowed=False,
                reason=f"System memory usage {snapshot.memory.usage_percent}% exceeds limit {max_memory}%",
            )
        
        return ResourceDecision(allowed=True)


def create_execution_mode_admission(
    runtime: ParikaRuntime,
    session: InterfaceSession,
) -> ExecutionModeAdmission:
    """Factory function to create ExecutionModeAdmission."""
    return ExecutionModeAdmission(runtime=runtime, session=session)
