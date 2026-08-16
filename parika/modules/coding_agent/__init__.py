"""
PARIKA Coding Agent Module package.

`coding.execute_task` is a pure orchestrator: it never implements
filesystem logic, shell execution, or indexing itself -- only Goal/
BrainRequest construction over the existing Planner/Brain/Coding Tool/
Filesystem Tool/Shell Tool. See
docs/development/Module_Guide.md section 8
and Addendum A section A.3.2 (pluggable `CodingAgent` registry).
"""

from __future__ import annotations

from .agent import CodingAgent, CodingAgentResult, CodingTaskDescriptor
from .driver import CodingAgentToolDriver
from .exceptions import (
    CodingAgentDepthExceededError,
    CodingAgentError,
    CodingAgentValidationRunFailedError,
    CodingPlanParsingError,
    CodingPlanValidationError,
    UnknownCodingAgentError,
)
from .manifest import (
    CODING_AGENT_MODULE_ID,
    CODING_AGENT_MODULE_VERSION,
    create_coding_agent_module,
    create_coding_agent_module_manifest,
)
from .module_driver import CodingAgentModuleDriver
from .registry import CodingAgentRegistry
from .standard_agent import StandardCodingAgent

__all__ = [
    "CODING_AGENT_MODULE_ID",
    "CODING_AGENT_MODULE_VERSION",
    "CodingAgent",
    "CodingAgentDepthExceededError",
    "CodingAgentError",
    "CodingAgentModuleDriver",
    "CodingAgentRegistry",
    "CodingAgentResult",
    "CodingAgentToolDriver",
    "CodingAgentValidationRunFailedError",
    "CodingPlanParsingError",
    "CodingPlanValidationError",
    "CodingTaskDescriptor",
    "StandardCodingAgent",
    "UnknownCodingAgentError",
    "create_coding_agent_module",
    "create_coding_agent_module_manifest",
]
