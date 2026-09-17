"""
PARIKA Autonomous Tool - Driver

Implements the Tool interface for autonomous mission operations.
Reads from the existing MissionRepository and AutonomousTaskRepository.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.repository import (
    MissionRepository,
    AutonomousTaskRepository,
)
from parika.core.autonomous.contracts import MissionStatus, AutonomousTaskStatus
from parika.core.database.pool import PoolManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.tool_manager.tool import Tool
from parika.tools.autonomous.manifest import (
    AUTONOMOUS_OPERATIONS,
    AutonomousOperation,
    AutonomousOperationSpec,
)


@dataclass(slots=True, kw_only=True)
class AutonomousTool:
    """
    Autonomous Tool driver.
    
    Implements mission.get_result and mission.list_tasks capabilities.
    Reads from the persistent autonomous execution repositories.
    """
    mission_repository: MissionRepository
    task_repository: AutonomousTaskRepository
    logger: Logger

    def execute(
        self,
        capability_id: str,
        inputs: MappingProxyType[str, Any],
        *,
        metadata: MappingProxyType[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute an autonomous tool capability.
        
        Args:
            capability_id: The capability to execute
            inputs: Input parameters for the capability
            metadata: Optional metadata
            
        Returns:
            Dictionary with the operation result
        """
        if capability_id == "mission.get_result":
            return self._get_mission_result(inputs)
        elif capability_id == "mission.list_tasks":
            return self._list_mission_tasks(inputs)
        else:
            return {
                "success": False,
                "error": f"Unknown capability: {capability_id}",
            }

    def _get_mission_result(self, inputs: MappingProxyType[str, Any]) -> dict[str, Any]:
        """Retrieve mission status, result, and failure information."""
        mission_id = inputs.get("mission_id")
        if not mission_id:
            return {
                "success": False,
                "error": "mission_id is required",
            }
        
        mission = self.mission_repository.get(mission_id)
        if mission is None:
            return {
                "success": False,
                "error": f"Mission '{mission_id}' not found",
            }
        
        return {
            "success": True,
            "mission_id": mission.id,
            "goal": mission.goal,
            "status": mission.status.value,
            "progress": mission.progress,
            "result": mission.result,
            "failure": mission.failure,
            "created_at": mission.created_at.isoformat() if mission.created_at else None,
            "started_at": mission.started_at.isoformat() if mission.started_at else None,
            "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        }

    def _list_mission_tasks(self, inputs: MappingProxyType[str, Any]) -> dict[str, Any]:
        """List all tasks for a mission with their status and results."""
        mission_id = inputs.get("mission_id")
        if not mission_id:
            return {
                "success": False,
                "error": "mission_id is required",
            }
        
        mission = self.mission_repository.get(mission_id)
        if mission is None:
            return {
                "success": False,
                "error": f"Mission '{mission_id}' not found",
            }
        
        tasks = self.task_repository.list_by_mission(mission_id)
        
        task_list = []
        for task in tasks:
            task_list.append({
                "task_id": task.id,
                "name": task.name,
                "description": task.description,
                "capability_id": task.capability_id,
                "status": task.status.value,
                "progress": task.progress,
                "result": task.result,
                "failure": task.failure,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            })
        
        return {
            "success": True,
            "mission_id": mission_id,
            "tasks": task_list,
        }


def create_autonomous_tool_driver(
    *,
    pool_manager: PoolManager,
    logger: Logger,
    event_bus: EventBus,
) -> AutonomousTool:
    """
    Factory function to create an AutonomousTool driver.
    
    Args:
        pool_manager: Database pool manager for repositories
        logger: PARIKA Logger component
        event_bus: Event bus for event publishing
        
    Returns:
        AutonomousTool driver instance
    """
    mission_repository = MissionRepository(pool_manager, logger)
    task_repository = AutonomousTaskRepository(pool_manager, logger)
    
    return AutonomousTool(
        mission_repository=mission_repository,
        task_repository=task_repository,
        logger=logger,
    )