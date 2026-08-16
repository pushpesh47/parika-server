"""
PARIKA Coding Agent - Standard Agent

`StandardCodingAgent` is the default, always-applicable `CodingAgent`
implementation, containing the orchestration logic
docs/development/Module_Guide.md sections
8.3-8.5 describe: assemble context -> submit an LLM-category
decomposition Goal -> validate the returned plan -> submit the
validated plan as an ordinary `BrainRequest` -> aggregate results.

It never implements filesystem logic, shell execution, or indexing
itself: every one of those eight steps is reached exclusively by
constructing `Goal`/`BrainRequest` objects and calling
`Brain.handle()`/`Brain.assemble_context()` -- both existing, already-
tested, entirely unmodified Core APIs.
"""

from __future__ import annotations

from uuid import uuid4

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.exceptions import ContextEngineUnavailableError
from parika.core.brain.goal_result import GoalResult
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.planner.goal import Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest

from .agent import CodingAgentResult, CodingTaskDescriptor
from .exceptions import CodingAgentValidationRunFailedError, CodingPlanParsingError
from .plan import CodingPlan, parse_plan_response, validate_plan

PLAN_CHANGE_CAPABILITY_ID = "coding.plan_change"

_PLAN_SYSTEM_PROMPT_TEMPLATE = """\
You are the planning stage of PARIKA's Coding Agent. Decompose the \
user's coding request into an ordered list of steps, each invoking \
exactly one PARIKA Capability from the allowed set below.

Allowed capability prefixes: coding., filesystem., shell.
Workspace root: {workspace_root}

Respond with ONLY a JSON object, no prose, no Markdown fences, \
matching exactly this schema:
{{"steps": [{{"id": "step_0", "capability_id": "coding.search", \
"inputs": {{"query": "..."}}, "depends_on": []}}, ...]}}

Every "path"/"cwd" input must stay inside the workspace root.
"""


class StandardCodingAgent:
    """
    The default, always-applicable Coding Agent.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        capability_registry: CapabilityRegistry,
        plan_capability_id: str = PLAN_CHANGE_CAPABILITY_ID,
    ) -> None:
        self._brain = brain
        self._capability_registry = capability_registry
        self._plan_capability_id = plan_capability_id

    @property
    def id(self) -> str:
        return "standard"

    def supports(self, task: CodingTaskDescriptor) -> bool:
        # Unconditional fallback -- always applicable.
        return True

    def execute(self, task: CodingTaskDescriptor) -> CodingAgentResult:
        plan, decomposition_result = self._decompose(task)

        known_capability_ids = frozenset(
            definition.id
            for definition in self._capability_registry.get_all()
            if definition.enabled
        )

        validate_plan(plan, task, known_capability_ids=known_capability_ids)

        goal_results = self._execute_plan(plan, task)

        if task.require_test_run:
            self._check_test_run(goal_results)

        return CodingAgentResult(
            summary=_build_summary(plan, goal_results),
            goal_results=(decomposition_result, *goal_results),
            metadata={"step_count": len(plan.steps)},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _decompose(self, task: CodingTaskDescriptor) -> tuple[CodingPlan, GoalResult]:
        goal_result = self._submit_decomposition_goal(task, correction=None)
        text = _extract_text(goal_result)

        try:
            return parse_plan_response(text), goal_result

        except CodingPlanParsingError as first_error:
            retry_result = self._submit_decomposition_goal(
                task, correction=str(first_error)
            )
            retry_text = _extract_text(retry_result)

            return parse_plan_response(retry_text), retry_result

    def _submit_decomposition_goal(
        self, task: CodingTaskDescriptor, *, correction: str | None
    ) -> GoalResult:
        system_prompt = _PLAN_SYSTEM_PROMPT_TEMPLATE.format(
            workspace_root=task.workspace_root
        )
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=task.instruction),
        ]

        if correction is not None:
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        "Your previous response could not be parsed: "
                        f"{correction}. Respond again with ONLY the "
                        "raw JSON object, no other text."
                    ),
                )
            )

        def _build_request(
            resolution: CapabilityResolution, model: ProviderModel
        ) -> ProviderRequest:
            return ChatRequest(messages=tuple(messages))

        execution_requirements = task.metadata.get("execution_requirements")

        goal = Goal(
            id=uuid4().hex,
            capability_id=self._plan_capability_id,
            inputs={"instruction": task.instruction},
            provider_request_builder=_build_request,
            metadata=(
                {"execution_requirements": execution_requirements}
                if execution_requirements is not None
                else {}
            ),
        )

        response = self._brain.handle(BrainRequest(goals=(goal,)))

        return response.results[0]

    def _execute_plan(
        self, plan: CodingPlan, task: CodingTaskDescriptor
    ) -> tuple[GoalResult, ...]:
        goals: list[Goal] = []
        previous_step_id: str | None = None

        for step in plan.steps:
            depends_on = step.depends_on or (
                (previous_step_id,) if previous_step_id else ()
            )
            metadata: dict[str, object] = {}

            if step.capability_id == "coding.execute_task":
                metadata["coding_agent_depth"] = task.depth + 1

            goals.append(
                Goal(
                    id=step.id,
                    capability_id=step.capability_id,
                    inputs=step.inputs,
                    depends_on=depends_on,
                    metadata=metadata,
                )
            )
            previous_step_id = step.id

        response = self._brain.handle(BrainRequest(goals=tuple(goals)))

        return response.results

    def _check_test_run(self, goal_results: tuple[GoalResult, ...]) -> None:
        for result in goal_results:
            if result.response is None:
                continue

            backend_response = result.response.outputs.get("result")
            payload = getattr(backend_response, "result", None)

            if isinstance(payload, dict) and "exit_code" in payload:
                if payload.get("exit_code") not in (0, None):
                    raise CodingAgentValidationRunFailedError(
                        f"Goal '{result.goal_id}' (test run) exited "
                        f"with code {payload.get('exit_code')}."
                    )


def _extract_text(goal_result: GoalResult) -> str:
    if not goal_result.succeeded or goal_result.response is None:
        raise CodingPlanParsingError(
            f"Decomposition Goal '{goal_result.goal_id}' did not "
            "succeed; no plan text is available."
        )

    backend_response = goal_result.response.outputs.get("result")

    if isinstance(backend_response, ChatResult):
        return backend_response.message.content

    return str(backend_response)


def _build_summary(plan: CodingPlan, goal_results: tuple[GoalResult, ...]) -> str:
    succeeded = sum(1 for result in goal_results if result.succeeded)
    skipped = sum(1 for result in goal_results if result.skipped)
    failed = len(goal_results) - succeeded - skipped

    return (
        f"Executed {len(plan.steps)} step(s): {succeeded} succeeded, "
        f"{failed} failed, {skipped} skipped."
    )
