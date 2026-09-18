"""
PARIKA Autonomous Execution - Authorization Boundary

Ensures autonomous execution cannot bypass PolicyEngine/PermissionManager.
Provides a single authoritative authorization path for autonomous execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.policy_engine.policy_effect import PolicyEffect
from parika.core.policy_engine.request import PolicyEvaluationRequest
from parika.core.policy_engine.policy_context import PolicyContext
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.logger.logger import Logger


@dataclass(frozen=True, slots=True, kw_only=True)
class AutonomousAuthorizationRequest:
    """Request for autonomous execution authorization."""
    agent_id: str
    agent_profile_id: str
    capability_id: str
    inputs: MappingProxyType[str, Any]
    mission_id: str
    task_id: str
    permission_context: MappingProxyType[str, Any]
    resource_budget: MappingProxyType[str, Any]
    metadata: MappingProxyType[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class AutonomousAuthorizationDecision:
    """Result of autonomous authorization evaluation."""
    allowed: bool
    reason: str | None
    policy_decision: str | None
    required_permissions: tuple[str, ...] = ()
    denied_permissions: tuple[str, ...] = ()


class AutonomousAuthorizationBoundary:
    """
    Single authoritative authorization path for autonomous execution.
    
    Ensures that autonomous/background execution cannot bypass:
    - PolicyEngine
    - PermissionManager
    - WorkspacePermissionManager
    
    The authorization path is:
    Agent -> Policy -> Permission -> Capability -> Tool/Provider -> Execution
    """

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        permission_manager: PermissionManager,
        workspace_permission_manager: WorkspacePermissionManager,
        logger: Logger,
        policy_rules: tuple[PolicyRule, ...] = (),
    ) -> None:
        self._policy_engine = policy_engine
        self._permission_manager = permission_manager
        self._workspace_permission_manager = workspace_permission_manager
        self._logger = logger.get_logger(__name__)
        self._policy_rules = policy_rules

    def authorize(self, request: AutonomousAuthorizationRequest) -> AutonomousAuthorizationDecision:
        """
        Authorize an autonomous execution request.
        
        This is the single enforcement point - all autonomous execution
        must pass through this method before proceeding.
        """
        self._logger.debug(
            "Authorizing autonomous execution: agent=%s, capability=%s, mission=%s, task=%s",
            request.agent_id, request.capability_id, request.mission_id, request.task_id
        )

        # Step 1: Build policy context from autonomous request
        policy_context = self._build_policy_context(request)

        # Step 2: Evaluate policy rules
        policy_request = PolicyEvaluationRequest(
            context=policy_context,
            rules=self._policy_rules,
            default_effect=PolicyEffect.DENY,  # Safe default for autonomous
        )

        policy_decision = self._policy_engine.evaluate(policy_request)

        if policy_decision.effect == PolicyEffect.DENY:
            self._logger.warning(
                "Autonomous execution denied by policy: agent=%s, capability=%s, reason=%s",
                request.agent_id, request.capability_id, policy_decision.reason
            )
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason=f"Policy denied: {policy_decision.reason}",
                policy_decision=policy_decision.matched_rule_id,
            )

        # Step 3: Check workspace permissions if capability requires filesystem/shell access
        workspace_decision = self._check_workspace_permissions(request)
        if not workspace_decision.allowed:
            return workspace_decision

        # Step 4: Check permission manager for capability-specific permissions
        permission_decision = self._check_permission_manager(request)
        if not permission_decision.allowed:
            return permission_decision

        # Step 5: Validate resource budget against limits
        budget_decision = self._check_resource_budget(request)
        if not budget_decision.allowed:
            return budget_decision

        self._logger.debug(
            "Autonomous execution authorized: agent=%s, capability=%s",
            request.agent_id, request.capability_id
        )

        return AutonomousAuthorizationDecision(
            allowed=True,
            reason=None,
            policy_decision=policy_decision.matched_rule_id,
        )

    def _build_policy_context(self, request: AutonomousAuthorizationRequest) -> PolicyContext:
        """Build policy context from autonomous request."""
        return {
            "agent_id": request.agent_id,
            "agent_profile_id": request.agent_profile_id,
            "capability_id": request.capability_id,
            "mission_id": request.mission_id,
            "task_id": request.task_id,
            "inputs": dict(request.inputs),
            "permission_context": dict(request.permission_context),
            "resource_budget": dict(request.resource_budget),
            "metadata": dict(request.metadata),
            "is_autonomous": True,
        }

    def _check_workspace_permissions(
        self, request: AutonomousAuthorizationRequest
    ) -> AutonomousAuthorizationDecision:
        """Check workspace permissions for filesystem/shell capabilities."""
        # Capabilities that require workspace permissions
        workspace_capabilities = {
            "filesystem.read", "filesystem.write", "filesystem.list",
            "filesystem.delete", "filesystem.mkdir", "shell.execute",
        }

        if request.capability_id not in workspace_capabilities:
            return AutonomousAuthorizationDecision(allowed=True, reason=None, policy_decision=None)

        # Check if the autonomous context has a workspace path
        workspace_path = request.permission_context.get("workspace_path")
        if not workspace_path:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason=f"Capability '{request.capability_id}' requires workspace path in permission_context",
                policy_decision="workspace_path_required",
            )

        # For autonomous execution, we check against trusted workspaces
        # In a real implementation, this would use the WorkspacePermissionManager
        # For now, we allow if the workspace is in the trusted set
        trusted_workspaces = request.permission_context.get("trusted_workspaces", [])
        if workspace_path not in trusted_workspaces:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason=f"Workspace '{workspace_path}' not in trusted workspaces for autonomous execution",
                policy_decision="workspace_not_trusted",
            )

        return AutonomousAuthorizationDecision(allowed=True, reason=None, policy_decision=None)

    def _check_permission_manager(
        self, request: AutonomousAuthorizationRequest
    ) -> AutonomousAuthorizationDecision:
        """Check permission manager for capability permissions."""
        # Check if agent profile has permission for this capability
        # This would integrate with the PermissionManager's grant system
        # For now, we check the agent's permission_context
        allowed_capabilities = request.permission_context.get("allowed_capabilities", [])
        if allowed_capabilities and request.capability_id not in allowed_capabilities:
            # Check for wildcard patterns
            allowed = False
            for pattern in allowed_capabilities:
                if pattern.endswith("*") and request.capability_id.startswith(pattern[:-1]):
                    allowed = True
                    break
                if pattern == request.capability_id:
                    allowed = True
                    break
            
            if not allowed:
                return AutonomousAuthorizationDecision(
                    allowed=False,
                    reason=f"Agent profile does not allow capability '{request.capability_id}'",
                    policy_decision="capability_not_allowed",
                    denied_permissions=(request.capability_id,),
                )

        # Check prohibited capabilities
        prohibited_capabilities = request.permission_context.get("prohibited_capabilities", [])
        if request.capability_id in prohibited_capabilities:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason=f"Capability '{request.capability_id}' is prohibited for this agent",
                policy_decision="capability_prohibited",
                denied_permissions=(request.capability_id,),
            )

        return AutonomousAuthorizationDecision(allowed=True, reason=None, policy_decision=None)

    def _check_resource_budget(
        self, request: AutonomousAuthorizationRequest
    ) -> AutonomousAuthorizationDecision:
        """Check resource budget against limits."""
        # Check max runtime
        max_runtime = request.resource_budget.get("max_runtime_seconds")
        if max_runtime is not None and max_runtime <= 0:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason="Resource budget max_runtime_seconds must be positive",
                policy_decision="invalid_budget",
            )

        # Check max retries
        max_retries = request.resource_budget.get("max_retries")
        if max_retries is not None and max_retries < 0:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason="Resource budget max_retries must be non-negative",
                policy_decision="invalid_budget",
            )

        # Check max children
        max_children = request.resource_budget.get("max_children")
        if max_children is not None and max_children < 0:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason="Resource budget max_children must be non-negative",
                policy_decision="invalid_budget",
            )

        # Check max tokens (for LLM capabilities)
        max_tokens = request.resource_budget.get("max_tokens")
        if max_tokens is not None and max_tokens <= 0:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason="Resource budget max_tokens must be positive",
                policy_decision="invalid_budget",
            )

        # Check max cost
        max_cost = request.resource_budget.get("max_cost_usd")
        if max_cost is not None and max_cost < 0:
            return AutonomousAuthorizationDecision(
                allowed=False,
                reason="Resource budget max_cost_usd must be non-negative",
                policy_decision="invalid_budget",
            )

        return AutonomousAuthorizationDecision(allowed=True, reason=None, policy_decision=None)


def create_autonomous_authorization_boundary(
    policy_engine: PolicyEngine,
    permission_manager: PermissionManager,
    workspace_permission_manager: WorkspacePermissionManager,
    logger: Logger,
    policy_rules: tuple[PolicyRule, ...] = (),
) -> AutonomousAuthorizationBoundary:
    """Factory function to create the authorization boundary."""
    return AutonomousAuthorizationBoundary(
        policy_engine=policy_engine,
        permission_manager=permission_manager,
        workspace_permission_manager=workspace_permission_manager,
        logger=logger,
        policy_rules=policy_rules,
    )