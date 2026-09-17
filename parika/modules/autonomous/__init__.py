"""
PARIKA Autonomous Module Package

Provides mission.get_result and mission.list_tasks capabilities for autonomous execution.
"""
from __future__ import annotations

from .driver import load_autonomous_module
from .manifest import AUTONOMOUS_MODULE_ID, AutonomousModuleDriver, create_autonomous_module

__all__ = [
    "AUTONOMOUS_MODULE_ID",
    "AutonomousModuleDriver",
    "create_autonomous_module",
    "load_autonomous_module",
]