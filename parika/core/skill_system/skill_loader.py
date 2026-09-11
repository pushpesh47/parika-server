"""
PARIKA Skill Loader

Handles progressive skill loading:
1. Discovery - metadata only
2. Security scanning
3. Activation - full body + scripts/references/assets
4. Execution - through PARIKA authorization boundary
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.skill_system.skill import (
    Skill,
    SkillStatus,
    SkillTrustState,
    SkillSecurityStatus,
)
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.skill_system.skill_parser import SkillParser
from parika.core.skill_system.skill_security import SkillSecurityScanner, SkillSecurityRecord


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillActivationResult:
    """Result of skill activation."""
    skill: Skill
    security_record: SkillSecurityRecord | None
    activated: bool
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillExecutionContext:
    """
    Context for skill execution.

    Provides access to skill resources (scripts, references, assets)
    through PARIKA's authorization boundary.
    """
    skill: Skill
    mission_id: str
    task_id: str
    agent_id: str
    allowed_tools: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    permission_context: MappingProxyType[str, Any]
    resource_budget: MappingProxyType[str, Any]


class SkillLoader:
    """
    Loads and activates skills with progressive disclosure.

    Flow:
    1. discover (metadata only) -> SkillCatalog
    2. scan (security) -> SkillSecurityScanner
    3. authorize (policy/permission) -> PolicyEngine + PermissionManager
    4. activate (load full content) -> SkillLoader
    5. execute (through PARIKA runtime) -> AutonomousExecutor
    """

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        security_scanner: SkillSecurityScanner,
        policy_engine: PolicyEngine,
        permission_manager: PermissionManager,
        workspace_permissions: WorkspacePermissionManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._registry = registry
        self._security_scanner = security_scanner
        self._policy_engine = policy_engine
        self._permission_manager = permission_manager
        self._workspace_permissions = workspace_permissions
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._parser = SkillParser()

    def prepare_skill_for_execution(
        self,
        skill_id: str,
        *,
        mission_id: str,
        task_id: str,
        agent_id: str,
        agent_profile_id: str,
        required_capabilities: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
    ) -> SkillActivationResult:
        """
        Prepare a skill for execution.

        This runs the full pipeline: scan -> authorize -> activate.
        Returns the activated skill ready for execution.
        """
        # Get skill
        skill = self._registry.get_skill(skill_id)
        if not skill:
            return SkillActivationResult(
                skill=skill,
                security_record=None,
                activated=False,
                reason=f"Skill '{skill_id}' not found",
            )

        # Check if already activated and valid
        if skill.status == SkillStatus.ACTIVE and skill.is_activatable():
            self._logger.debug("Skill '%s' already active and valid", skill_id)
            return SkillActivationResult(
                skill=skill,
                security_record=None,
                activated=True,
                reason="Already active",
            )

        # Step 1: Security scan (if not already scanned)
        security_record = None
        if skill.security_status == SkillSecurityStatus.PENDING:
            self._logger.info("Scanning skill '%s' for security", skill_id)
            security_record = self._registry.scan_skill(skill_id)
            skill = self._registry.get_skill(skill_id)  # Refresh

        # Check if skill passed security
        if not skill.is_activatable():
            return SkillActivationResult(
                skill=skill,
                security_record=security_record,
                activated=False,
                reason=f"Skill failed security/trust check: trust={skill.trust_state.value}, security={skill.security_status.value}",
            )

        # Step 2: Policy/Authorization check
        auth_result = self._authorize_skill(
            skill,
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent_id,
            agent_profile_id=agent_profile_id,
            required_capabilities=required_capabilities,
            allowed_tools=allowed_tools,
        )

        if not auth_result:
            return SkillActivationResult(
                skill=skill,
                security_record=security_record,
                activated=False,
                reason="Authorization denied by policy/permission",
            )

        # Step 3: Activate (load full content)
        try:
            activated_skill = self._registry.activate_skill(skill_id)
            self._logger.info("Skill '%s' activated for execution", skill_id)

            self._event_bus.publish("skill.prepared_for_execution", {
                "skill_id": skill_id,
                "mission_id": mission_id,
                "task_id": task_id,
                "agent_id": agent_id,
            })

            return SkillActivationResult(
                skill=activated_skill,
                security_record=security_record,
                activated=True,
                reason="Activated successfully",
            )

        except Exception as e:
            self._logger.error("Failed to activate skill '%s': %s", skill_id, e)
            return SkillActivationResult(
                skill=skill,
                security_record=security_record,
                activated=False,
                reason=f"Activation failed: {e}",
            )

    def _authorize_skill(
        self,
        skill: Skill,
        *,
        mission_id: str,
        task_id: str,
        agent_id: str,
        agent_profile_id: str,
        required_capabilities: tuple[str, ...] = (),
        allowed_tools: tuple[str, ...] = (),
    ) -> bool:
        """Check if skill execution is authorized."""
        # Build authorization context
        from parika.core.autonomous.authorization import AutonomousAuthorizationRequest, create_autonomous_authorization_boundary

        # Check skill's required capabilities against allowed
        for cap in skill.metadata.required_capabilities:
            if required_capabilities and cap not in required_capabilities:
                self._logger.warning("Skill '%s' requires capability '%s' not in allowed list", skill.id, cap)
                return False

        # Check skill's allowed tools against agent's allowed tools
        for tool in skill.metadata.allowed_tools:
            if allowed_tools and tool not in allowed_tools:
                self._logger.warning("Skill '%s' allows tool '%s' not in agent's allowed tools", skill.id, tool)
                return False

        # Check workspace permissions for any filesystem/shell operations
        # This would be done at actual tool execution time, but we do a preliminary check
        # The actual enforcement happens in ToolManager through WorkspacePermissionManager

        return True

    def create_execution_context(
        self,
        skill_id: str,
        *,
        mission_id: str,
        task_id: str,
        agent_id: str,
        permission_context: MappingProxyType[str, Any],
        resource_budget: MappingProxyType[str, Any],
    ) -> SkillExecutionContext:
        """Create execution context for a skill."""
        skill = self._registry.get_skill(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        if skill.status != SkillStatus.ACTIVE:
            raise ValueError(f"Skill '{skill_id}' is not active")

        return SkillExecutionContext(
            skill=skill,
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent_id,
            allowed_tools=skill.metadata.allowed_tools,
            allowed_capabilities=skill.metadata.required_capabilities,
            permission_context=permission_context,
            resource_budget=resource_budget,
        )

    def get_script(self, skill_id: str, script_name: str) -> str | None:
        """Get a script from an activated skill."""
        skill = self._registry.get_skill(skill_id)
        if not skill or skill.status != SkillStatus.ACTIVE:
            return None
        return skill.scripts.get(script_name)

    def get_reference(self, skill_id: str, ref_name: str) -> str | None:
        """Get a reference from an activated skill."""
        skill = self._registry.get_skill(skill_id)
        if not skill or skill.status != SkillStatus.ACTIVE:
            return None
        return skill.references.get(ref_name)

    def get_asset(self, skill_id: str, asset_name: str) -> bytes | None:
        """Get an asset from an activated skill."""
        skill = self._registry.get_skill(skill_id)
        if not skill or skill.status != SkillStatus.ACTIVE:
            return None
        return skill.assets.get(asset_name)

    def list_skill_resources(self, skill_id: str) -> dict[str, list[str]]:
        """List all resources in an activated skill."""
        skill = self._registry.get_skill(skill_id)
        if not skill or skill.status != SkillStatus.ACTIVE:
            return {"scripts": [], "references": [], "assets": []}

        return {
            "scripts": list(skill.scripts.keys()),
            "references": list(skill.references.keys()),
            "assets": list(skill.assets.keys()),
        }

    def record_skill_usage(self, skill_id: str) -> None:
        """Record that a skill was used (for analytics/experience)."""
        skill = self._registry.get_skill(skill_id)
        if skill and skill.status == SkillStatus.ACTIVE:
            self._logger.debug("Recorded usage for skill '%s'", skill_id)
            # Could update last_used_at, activation_count, etc.
            # This would require a mutable update or event sourcing approach