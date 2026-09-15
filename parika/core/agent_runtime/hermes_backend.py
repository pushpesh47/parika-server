"""
PARIKA Hermes Execution Backend

Implements ExecutionBackend for Hermes agent execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.execution_backend import (
    BackendExecutionContext,
    BackendExecutionResult,
    ExecutionBackend,
)
from parika.core.autonomous.execution_strategy import ExecutionStrategy
from parika.core.autonomous.authorization import AutonomousAuthorizationBoundary, AutonomousAuthorizationRequest
from parika.core.skill_system.skill_loader import SkillLoader
from parika.core.skill_system.skill_registry import SkillRegistry
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


class HermesBackend(ExecutionBackend):
    """
    Hermes execution backend.
    
    Executes Hermes agents as isolated processes using `hermes chat --oneshot -Q`.
    """

    def __init__(
        self,
        *,
        authorization_boundary: AutonomousAuthorizationBoundary,
        skill_loader: SkillLoader,
        skill_registry: SkillRegistry,
        permission_manager: PermissionManager,
        workspace_permissions: WorkspacePermissionManager,
        resource_manager: ResourceManager,
        event_bus: EventBus,
        logger: Logger,
        hermes_binary: str = "hermes",
        hermes_config_dir: str | None = None,
    ) -> None:
        self._authorization_boundary = authorization_boundary
        self._skill_loader = skill_loader
        self._skill_registry = skill_registry
        self._permission_manager = permission_manager
        self._workspace_permissions = workspace_permissions
        self._resource_manager = resource_manager
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._hermes_binary = hermes_binary
        self._hermes_config_dir = hermes_config_dir or os.path.expanduser("~/.hermes")

    @property
    def backend_type(self) -> str:
        return "hermes"

    async def execute(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
    ) -> BackendExecutionResult:
        """Execute a capability in Hermes runtime."""
        import time
        start_time = time.perf_counter()
        
        try:
            self._logger.info(
                "Hermes backend executing capability '%s' for task '%s'",
                strategy.capability_id, context.task_id
            )

            # Build authorization request
            auth_request = AutonomousAuthorizationRequest(
                agent_id=context.agent_id,
                agent_profile_id=context.agent_profile_id,
                capability_id=strategy.capability_id,
                inputs=inputs,
                mission_id=context.mission_id,
                task_id=context.task_id,
                permission_context=context.permission_context,
                resource_budget=context.resource_budget,
            )

            # Check authorization
            auth_decision = self._authorization_boundary.authorize(auth_request)
            if not auth_decision.allowed:
                raise PermissionError(f"Authorization denied: {auth_decision.reason}")

            # Check resource budget
            if not self._check_resource_budget(context.resource_budget):
                raise RuntimeError("Resource budget exceeded")

            # Load skill if specified
            skill_context = ""
            skill_id = context.permission_context.get("skill_id")
            if skill_id:
                skill_result = self._skill_loader.prepare_skill_for_execution(
                    skill_id,
                    mission_id=context.mission_id,
                    task_id=context.task_id,
                    agent_id=context.agent_id,
                    agent_profile_id=context.agent_profile_id,
                )
                if not skill_result.activated:
                    raise RuntimeError(f"Skill activation failed: {skill_result.reason}")
                skill_context = self._build_skill_context(skill_result.skill)

            # Build Hermes command for oneshot execution
            cmd = [
                self._hermes_binary,
                "chat",
                "--oneshot",
                "-Q",  # Quiet mode - only output final response
            ]

            # Add config dir if specified
            if self._hermes_config_dir:
                cmd.extend(["--config-dir", self._hermes_config_dir])

            # Build the prompt
            prompt = self._build_prompt(strategy.capability_id, inputs, skill_context)

            # Execute Hermes as oneshot
            timeout = context.resource_budget.get("timeout_seconds", 300.0)

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=Path(self._hermes_config_dir).parent if self._hermes_config_dir else None,
                )

                # Send prompt via stdin
                if process.stdin:
                    process.stdin.write(prompt.encode())
                    await process.stdin.drain()
                    process.stdin.close()

                # Wait for result with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )

                if process.returncode != 0:
                    stderr_str = stderr.decode() if stderr else "Unknown error"
                    raise RuntimeError(f"Hermes execution failed (code {process.returncode}): {stderr_str}")

                # Parse result
                output = stdout.decode().strip() if stdout else ""
                result = self._parse_hermes_oneshot_output(output)

                execution_time_ms = (time.perf_counter() - start_time) * 1000

                # Record successful execution
                self._event_bus.publish("hermes.execution.completed", {
                    "agent_id": context.agent_id,
                    "task_id": context.task_id,
                    "capability_id": strategy.capability_id,
                })

                return BackendExecutionResult(
                    success=True,
                    result=result,
                    execution_time_ms=execution_time_ms,
                )

            except asyncio.TimeoutError:
                raise TimeoutError(f"Hermes execution timed out after {timeout}s")

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            self._logger.exception(
                "Hermes backend execution failed for capability '%s': %s",
                strategy.capability_id, e
            )
            return BackendExecutionResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time_ms,
            )

    def _parse_hermes_oneshot_output(self, output: str) -> MappingProxyType[str, Any]:
        """Parse Hermes oneshot output into structured result."""
        return MappingProxyType({
            "output": output,
            "success": True,
            "raw_output": output,
        })

    def _build_prompt(
        self,
        capability_id: str,
        inputs: MappingProxyType[str, Any],
        skill_context: str,
    ) -> str:
        """Build prompt for Hermes."""
        parts = []

        if skill_context:
            parts.append(f"[SKILL CONTEXT]\n{skill_context}\n")

        parts.append(f"[CAPABILITY] {capability_id}")
        parts.append(f"[INPUTS] {json.dumps(dict(inputs), indent=2)}")

        return "\n".join(parts)

    def _build_skill_context(self, skill) -> str:
        """Build skill context for Hermes."""
        parts = [
            f"Skill: {skill.metadata.name}",
            f"Description: {skill.metadata.description}",
            f"Version: {skill.metadata.version}",
        ]

        if skill.body:
            parts.append(f"Instructions:\n{skill.body}")

        if skill.metadata.allowed_tools:
            parts.append(f"Allowed Tools: {', '.join(skill.metadata.allowed_tools)}")

        if skill.metadata.required_capabilities:
            parts.append(f"Required Capabilities: {', '.join(skill.metadata.required_capabilities)}")

        return "\n".join(parts)

    def _check_resource_budget(self, budget: MappingProxyType[str, Any]) -> bool:
        """Check if execution fits within resource budget."""
        # Simple check - would integrate with BudgetEnforcer
        return True

    def is_available(self) -> bool:
        """Check if Hermes binary is available."""
        try:
            result = subprocess.run(
                [self._hermes_binary, "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    async def health_check(self) -> bool:
        """Health check - validate Hermes binary and config."""
        return self.is_available()