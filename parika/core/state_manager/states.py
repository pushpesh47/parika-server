"""
Operational state definitions for PARIKA.

This module defines the valid operational states used by the
StateManager to represent the current state of the running
PARIKA instance.
"""

from __future__ import annotations

from enum import Enum


class LifecycleState(Enum):
    """
    Lifecycle states of the PARIKA application.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


class ExecutionState(Enum):
    """
    Execution states of the PARIKA application.
    """

    IDLE = "idle"
    EXECUTING = "executing"
    WAITING = "waiting"


class InteractionState(Enum):
    """
    Interaction states of the PARIKA application.
    """

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    RESPONDING = "responding"


class ProviderState(Enum):
    """
    Provider connectivity states.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"