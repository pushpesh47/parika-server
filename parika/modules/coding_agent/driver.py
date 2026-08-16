"""
PARIKA Coding Agent - Driver

Implements the `ToolDriver` contract for the single, stable
`tool.coding_execute_task` Tool (capability `coding.execute_task`).
This driver is a pure dispatcher: it builds a `CodingTaskDescriptor`,
asks `CodingAgentRegistry` for the matching `CodingAgent`
implementation, and delegates. It never implements filesystem logic,
shell execution, or indexing itself.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from .agent import CodingTaskDescriptor
from .exceptions import CodingAgentError, CodingPlanValidationError
from .registry import CodingAgentRegistry

CODING_AGENT_DEPTH_METADATA_KEY = "coding_agent_depth"


class CodingAgentToolDriver:
    """
    `ToolDriver` implementing `coding.execute_task`.
    """

    def __init__(
        self,
        *,
        registry: CodingAgentRegistry,
        default_workspace: Path,
        default_max_depth: int = 3,
        allowed_write_roots: tuple[Path, ...] = (),
        require_test_run: bool = False,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._registry = registry
        self._default_workspace = default_workspace
        self._default_max_depth = default_max_depth
        self._allowed_write_roots = allowed_write_roots
        self._require_test_run = require_test_run
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter("coding.execute_task")
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        instruction = str(request.arguments.get("instruction", "")).strip()

        if not instruction:
            raise CodingAgentError(
                "request.arguments['instruction'] must be a non-empty string."
            )

        workspace_root = Path(
            str(request.arguments.get("workspace_root", self._default_workspace))
        )
        depth = int(request.metadata.get(CODING_AGENT_DEPTH_METADATA_KEY, 0))

        execution_requirements = request.metadata.get("execution_requirements")

        task = CodingTaskDescriptor(
            instruction=instruction,
            workspace_root=workspace_root,
            requested_agent_id=request.arguments.get("agent"),
            max_depth=int(request.arguments.get("max_depth", self._default_max_depth)),
            depth=depth,
            allowed_write_roots=self._allowed_write_roots,
            require_test_run=bool(
                request.arguments.get("require_test_run", self._require_test_run)
            ),
            metadata=(
                {"execution_requirements": execution_requirements}
                if execution_requirements is not None
                else {}
            ),
        )

        self._progress.started(message="Selecting coding agent...")

        try:
            agent = (
                self._registry.get(task.requested_agent_id)
                if task.requested_agent_id
                else self._registry.select(task)
            )

            self._progress.progress(message=f"Waiting for model... (agent={agent.id})")

            result = agent.execute(task)

        except CodingPlanValidationError as ex:
            self._progress.failed(message=str(ex))

            return ToolResponse(
                result={"validated": False, "reason": str(ex)},
                attributes={"rejected": True},
            )

        except Exception:
            self._progress.failed()
            raise

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "validated": True,
                "succeeded": result.succeeded,
                "summary": result.summary,
                "step_count": result.metadata.get("step_count"),
            },
            attributes={"agent_id": agent.id},
        )
