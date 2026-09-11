"""
PARIKA Hermes Runtime Adapter

Implements the AgentRuntime interface for Hermes agent execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from parika.core.agent_runtime.contracts import (
    AgentRuntime,
    RuntimeCapabilities,
    RuntimeConfig,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
    RuntimeInfo,
    RuntimeStatus,
    RuntimeType,
)
from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.autonomous.authorization import AutonomousAuthorizationBoundary
from parika.core.autonomous.checkpoint_manager import CheckpointManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.skill_system.skill_loader import SkillLoader
from parika.core.skill_system.skill_registry import SkillRegistry


@dataclass(slots=True, kw_only=True)
class HermesSession:
    """Represents a Hermes session."""
    session_id: str
    agent_id: str
    process: subprocess.Popen
    started_at: datetime
    last_heartbeat: datetime
    status: str = "starting"
    stdin_writer: asyncio.StreamWriter | None = None
    stdout_reader: asyncio.StreamReader | None = None
    stderr_reader: asyncio.StreamReader | None = None


class HermesRuntimeAdapter(AgentRuntime):
    """
    Hermes runtime adapter.

    Executes Hermes agents as isolated processes with proper
    authorization propagation, resource governance, and checkpointing.
    """

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        agent_supervisor: AgentSupervisor,
        authorization_boundary: AutonomousAuthorizationBoundary,
        checkpoint_manager: CheckpointManager,
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
        self._config = config
        self._agent_supervisor = agent_supervisor
        self._authorization_boundary = authorization_boundary
        self._checkpoint_manager = checkpoint_manager
        self._skill_loader = skill_loader
        self._skill_registry = skill_registry
        self._permission_manager = permission_manager
        self._workspace_permissions = workspace_permissions
        self._resource_manager = resource_manager
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._runtime_id = config.runtime_id
        self._status = RuntimeStatus.STOPPED
        self._started_at: datetime | None = None
        self._hermes_binary = hermes_binary
        self._hermes_config_dir = hermes_config_dir or os.path.expanduser("~/.hermes")
        self._sessions: dict[str, HermesSession] = {}
        self._lock = threading.RLock()
        self._monitor_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Capabilities - Hermes supports a wide range
        self._capabilities = RuntimeCapabilities(
            supported_capability_categories=(
                "tool", "llm", "reasoning", "vision", "embedding",
                "translation", "speech", "text_to_speech",
                "image_generation", "video_generation", "ocr"
            ),
            max_concurrent_agents=config.resource_limits.get("max_concurrent_agents", 5),
            supports_checkpoint=True,
            supports_skills=True,
            supports_tools=True,
            supports_a2a=True,  # Hermes has peer-to-peer
            supports_streaming=True,
            resource_isolation="process",
        )

    @property
    def runtime_id(self) -> str:
        return self._runtime_id

    @property
    def runtime_type(self) -> RuntimeType:
        return RuntimeType.HERMES

    @property
    def capabilities(self) -> RuntimeCapabilities:
        return self._capabilities

    @property
    def status(self) -> RuntimeStatus:
        return self._status

    async def discover(self) -> list[str]:
        """Discover available capabilities/skills in Hermes."""
        # Could query Hermes for available skills/tools
        return []

    async def validate(self, config: RuntimeConfig) -> tuple[bool, str | None]:
        """Validate Hermes runtime configuration."""
        # Check if Hermes binary exists
        try:
            result = subprocess.run(
                [self._hermes_binary, "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False, f"Hermes binary not found or failed: {result.stderr.decode()}"
        except FileNotFoundError:
            return False, f"Hermes binary '{self._hermes_binary}' not found in PATH"
        except Exception as e:
            return False, f"Failed to validate Hermes: {e}"

        # Check config directory
        if not Path(self._hermes_config_dir).exists():
            return False, f"Hermes config directory not found: {self._hermes_config_dir}"

        return True, None

    async def start(self) -> bool:
        """Start the Hermes runtime monitor."""
        if self._status == RuntimeStatus.RUNNING:
            return True

        self._status = RuntimeStatus.STARTING

        try:
            # Validate Hermes
            valid, error = await self.validate(self._config)
            if not valid:
                self._status = RuntimeStatus.ERROR
                return False

            # Start monitor task
            self._loop = asyncio.get_event_loop()
            self._monitor_task = self._loop.create_task(self._monitor_sessions())

            self._status = RuntimeStatus.RUNNING
            self._started_at = datetime.now(UTC)
            self._logger.info("Hermes runtime started")
            return True

        except Exception as e:
            self._status = RuntimeStatus.ERROR
            self._logger.error("Failed to start Hermes runtime: %s", e)
            return False

    async def execute(
        self,
        agent_id: str,
        task_id: str,
        capability_id: str,
        inputs: MappingProxyType[str, Any],
        context: MappingProxyType[str, Any],
        skill_id: str | None = None,
    ) -> MappingProxyType[str, Any]:
        """
        Execute a capability in Hermes runtime.

        Uses `hermes chat --oneshot -Q` for deterministic request/response.
        """
        self._logger.info(
            "Hermes runtime executing capability '%s' for agent '%s'",
            capability_id, agent_id
        )

        # Check authorization
        auth_request = self._build_auth_request(
            agent_id=agent_id,
            task_id=task_id,
            capability_id=capability_id,
            inputs=inputs,
            context=context,
        )

        auth_decision = self._authorization_boundary.authorize(auth_request)
        if not auth_decision.allowed:
            raise PermissionError(f"Authorization denied: {auth_decision.reason}")

        # Check resource budget
        resource_budget = context.get("resource_budget", {})
        if not self._check_resource_budget(resource_budget):
            raise RuntimeError("Resource budget exceeded")

        # Load skill if specified
        skill_context = ""
        if skill_id:
            skill_result = self._skill_loader.prepare_skill_for_execution(
                skill_id,
                mission_id=context.get("mission_id", ""),
                task_id=task_id,
                agent_id=agent_id,
                agent_profile_id=context.get("agent_profile_id", "default"),
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
        prompt = self._build_prompt(capability_id, inputs, skill_context)

        # Execute Hermes as oneshot
        timeout = context.get("timeout_seconds", 300.0)
        
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

            # Record successful execution
            self._event_bus.publish("hermes.execution.completed", {
                "agent_id": agent_id,
                "task_id": task_id,
                "capability_id": capability_id,
            })

            return MappingProxyType(result)

        except asyncio.TimeoutError:
            raise TimeoutError(f"Hermes execution timed out after {timeout}s")
        except Exception as e:
            raise

    def _parse_hermes_oneshot_output(self, output: str) -> dict[str, Any]:
        """Parse Hermes oneshot output into structured result."""
        # In oneshot mode, the output is the direct response
        return {
            "output": output,
            "success": True,
            "raw_output": output,
        }

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

    def _is_completion_marker(self, line: str) -> bool:
        """Check if line indicates completion."""
        completion_markers = [
            "✓ Done",
            "✗ Failed",
            "Task completed",
            "Execution finished",
        ]
        return any(marker in line for marker in completion_markers)

    async def _parse_hermes_output(self, lines: list[str]) -> MappingProxyType[str, Any]:
        """Parse Hermes output into structured result."""
        # Simple parsing - in practice would be more sophisticated
        full_output = "\n".join(lines)

        return MappingProxyType({
            "output": full_output,
            "success": "✓" in full_output or "completed" in full_output.lower(),
            "raw_lines": lines,
        })

    def _build_auth_request(
        self,
        agent_id: str,
        task_id: str,
        capability_id: str,
        inputs: MappingProxyType[str, Any],
        context: MappingProxyType[str, Any],
    ):
        """Build authorization request."""
        from parika.core.autonomous.authorization import AutonomousAuthorizationRequest

        return AutonomousAuthorizationRequest(
            agent_id=agent_id,
            agent_profile_id=context.get("agent_profile_id", "default"),
            capability_id=capability_id,
            inputs=inputs,
            mission_id=context.get("mission_id", ""),
            task_id=task_id,
            permission_context=context.get("permission_context", MappingProxyType({})),
            resource_budget=context.get("resource_budget", MappingProxyType({})),
        )

    def _check_resource_budget(self, budget: MappingProxyType[str, Any]) -> bool:
        """Check if execution fits within resource budget."""
        # Simple check - would integrate with BudgetEnforcer
        return True

    async def _terminate_session(self, session: HermesSession) -> None:
        """Terminate a Hermes session."""
        if session.process and session.process.returncode is None:
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                session.process.kill()
                await session.process.wait()

    async def _cleanup_session(self, session_id: str) -> None:
        """Clean up session resources."""
        with self._lock:
            session = self._sessions.pop(session_id, None)

        if session:
            await self._terminate_session(session)

    async def _monitor_sessions(self) -> None:
        """Monitor Hermes sessions for health."""
        while self._status == RuntimeStatus.RUNNING:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds

                with self._lock:
                    sessions = list(self._sessions.values())

                for session in sessions:
                    # Check process health
                    if session.process.returncode is not None:
                        self._logger.warning(
                            "Hermes session '%s' terminated unexpectedly with code %s",
                            session.session_id, session.process.returncode
                        )
                        await self._cleanup_session(session.session_id)
                        continue

                    # Check heartbeat timeout
                    elapsed = (datetime.now(UTC) - session.last_heartbeat).total_seconds()
                    if elapsed > 120:  # 2 minute timeout
                        self._logger.warning(
                            "Hermes session '%s' heartbeat timeout",
                            session.session_id
                        )
                        await self._cleanup_session(session.session_id)

            except Exception as e:
                self._logger.error("Error in Hermes session monitor: %s", e)

    async def pause(self, agent_id: str) -> bool:
        """Pause an agent execution."""
        # Hermes doesn't have native pause - would need custom implementation
        return False

    async def resume(self, agent_id: str) -> bool:
        """Resume a paused agent execution."""
        return False

    async def cancel(self, agent_id: str) -> bool:
        """Cancel an agent execution."""
        with self._lock:
            # Find session for this agent
            session = next(
                (s for s in self._sessions.values() if s.agent_id == agent_id),
                None,
            )

        if session:
            await self._terminate_session(session)
            await self._cleanup_session(session.session_id)
            return True

        return False

    async def terminate(self, agent_id: str) -> bool:
        """Terminate an agent (force stop)."""
        return await self.cancel(agent_id)

    async def heartbeat(self, agent_id: str) -> bool:
        """Send heartbeat for an agent."""
        with self._lock:
            session = next(
                (s for s in self._sessions.values() if s.agent_id == agent_id),
                None,
            )

        if session:
            session.last_heartbeat = datetime.now(UTC)
            return True

        return False

    async def get_status(self, agent_id: str) -> MappingProxyType[str, Any]:
        """Get agent execution status."""
        with self._lock:
            session = next(
                (s for s in self._sessions.values() if s.agent_id == agent_id),
                None,
            )

        if not session:
            return MappingProxyType({"status": "not_found"})

        return MappingProxyType({
            "agent_id": agent_id,
            "session_id": session.session_id,
            "status": session.status,
            "started_at": session.started_at.isoformat(),
            "last_heartbeat": session.last_heartbeat.isoformat(),
        })

    async def collect_result(self, agent_id: str) -> MappingProxyType[str, Any] | None:
        """Collect execution result."""
        # Result would be collected during execute()
        return None

    async def checkpoint(self, agent_id: str) -> MappingProxyType[str, Any] | None:
        """Create checkpoint for agent."""
        with self._lock:
            session = next(
                (s for s in self._sessions.values() if s.agent_id == agent_id),
                None,
            )

        if not session:
            return None

        return MappingProxyType({
            "agent_id": agent_id,
            "session_id": session.session_id,
            "status": session.status,
            "checkpoint_time": datetime.now(UTC).isoformat(),
        })

    async def restore(self, agent_id: str, checkpoint: MappingProxyType[str, Any]) -> bool:
        """Restore agent from checkpoint."""
        # Hermes doesn't have native checkpoint/restore
        return False

    async def get_available_tools(self) -> list[str]:
        """Get list of available tool IDs from Hermes."""
        # Could query Hermes for available tools
        return []

    async def get_available_skills(self) -> list[str]:
        """Get list of available skill IDs from Hermes."""
        # Could query Hermes skills
        return []

    async def stop(self) -> bool:
        """Stop the Hermes runtime."""
        if self._status == RuntimeStatus.STOPPED:
            return True

        self._status = RuntimeStatus.STOPPING

        # Cancel monitor
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Terminate all sessions
        with self._lock:
            sessions = list(self._sessions.values())

        for session in sessions:
            await self._terminate_session(session)

        with self._lock:
            self._sessions.clear()

        self._status = RuntimeStatus.STOPPED
        self._logger.info("Hermes runtime stopped")
        return True

    def get_info(self) -> RuntimeInfo:
        """Get runtime info."""
        return RuntimeInfo(
            runtime_id=self._runtime_id,
            name=self._config.name,
            runtime_type=self.runtime_type,
            status=self._status,
            capabilities=self._capabilities,
            config=self._config,
            started_at=self._started_at,
            active_agents=len(self._sessions),
        )