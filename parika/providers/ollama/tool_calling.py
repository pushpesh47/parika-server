"""
PARIKA Ollama Provider - Tool Call Resolution

Resolves a single tool call requested by an Ollama model by invoking
the mapped PARIKA Capability through `Brain.handle()`.

This is the only place the Ollama provider ever executes a requested
capability: it always goes through Brain, which itself always goes
through Planner, so capability resolution, policy evaluation, and
Tool/Provider selection are never bypassed (see
`PARIKA_Decision_Flow.md` section 4.4 and `Running.md` section 8.3).
Kept separate from `driver.py` so the driver itself stays focused on
orchestration (see `PARIKA_Core_Coding_Standards.md` - File Size
Guidelines).

Also owns extracting the one reserved, generic `model_selection_hint`
tool-call argument (see `parika/interfaces/ai_context
/model_selection_policy.py` for the policy text describing it to the
routing model), and forwarding it as this Goal's own `Goal.metadata
["execution_requirements"]` override -- the same, pre-existing
extension point `ai_context.goal_builder.build_chat_goal()` already
uses for the outer chat Goal. This is the single, universal capture
point for every current and future Tool: `ToolRequest.metadata`
(already part of `ToolManager`'s public shape, previously always
empty) is what carries it onward to whichever Tool driver receives
this call (see `Planner._select_tool()`, unmodified). A Tool driver
that never reads `ToolRequest.metadata` is completely unaffected; only
a two-step Tool driver that itself submits a nested, Provider-backed
Goal (e.g. `VisionToolDriver`, `OcrToolDriver`) needs to forward it
onward to that inner Goal to actually influence Model Selection.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.logger.logger import Logger
from parika.core.planner.goal import Goal

from .messages import OllamaToolCall, OllamaToolSpec
from .wire import serialize_task_result

MODEL_SELECTION_HINT_ARGUMENT = "model_selection_hint"
"""
The one reserved, generic tool-call argument name a routing model may
optionally supply on any tool call (see `model_selection_policy.py`).
Never a required argument, and never validated against a specific
Tool's own JSON schema -- it is popped out of `call.arguments` before
that Tool ever sees its own arguments.
"""


def _extract_execution_requirements_override(
    arguments: dict[str, object],
) -> Mapping[str, object] | None:
    """
    Pop `MODEL_SELECTION_HINT_ARGUMENT` out of `arguments` (in place,
    so the Tool this call actually targets never sees it as one of its
    own arguments) and translate it into a `Goal.metadata
    ["execution_requirements"]`-shaped override mapping.

    Defensive by construction, exactly like every other optional
    signal in the Model Selection Framework: a missing, malformed, or
    partially-malformed hint never raises and simply contributes
    nothing. `candidate_models` is placed under the override's own
    `"metadata"` key (never a first-class `ExecutionRequirements`
    field -- see `RoutingRecommendationRule`'s docstring for why a
    recommendation is deliberately not modeled as a requirement).
    `reasoning_level`, by contrast, is a genuine, pre-existing
    `ExecutionRequirements` field, so it is forwarded as a plain
    top-level override key exactly like any other explicit override
    value already is.

    Returns:
        `None` when there is nothing to override (no hint supplied,
        or the hint carried no recognizable field) -- the caller
        builds the Goal with no `metadata` at all in that case,
        identical to today's behavior.
    """

    hint = arguments.pop(MODEL_SELECTION_HINT_ARGUMENT, None)

    if not isinstance(hint, Mapping):
        return None

    execution_requirements: dict[str, object] = {}

    candidate_models = hint.get("candidate_models")

    if isinstance(candidate_models, (list, tuple)):
        execution_requirements["metadata"] = {
            "candidate_models": list(candidate_models)
        }

    reasoning_level = hint.get("reasoning_level")

    if isinstance(reasoning_level, str) and reasoning_level:
        execution_requirements["reasoning_level"] = reasoning_level

    if not execution_requirements:
        return None

    return execution_requirements


class ToolCallResolver:
    """
    Resolves Ollama tool calls into Brain-executed capability results.
    """

    def __init__(self, *, logger: Logger) -> None:
        """
        Initialize the resolver.

        Args:
            logger:
                PARIKA Logger component.
        """

        self._logger = logger.get_logger(__name__)
        self._brain: Brain | None = None

    def bind_brain(self, brain: Brain) -> None:
        """
        Bind the Brain used to resolve tool calls.
        """

        self._brain = brain

    @property
    def is_bound(self) -> bool:
        """
        Whether a Brain has been bound.
        """

        return self._brain is not None

    def resolve(
        self,
        call: OllamaToolCall,
        tools_by_name: dict[str, OllamaToolSpec],
    ) -> tuple[str, str | None, bool]:
        """
        Resolve a single tool call requested by the model.

        Args:
            call:
                The tool call requested by the model.

            tools_by_name:
                Every tool specification advertised for this chat
                request, keyed by the name advertised to the model.

        Returns:
            A `(content, capability_id, succeeded)` triple. `content`
            is always a JSON string suitable for feeding back to the
            model as a "tool" role message.
        """

        spec = tools_by_name.get(call.name)

        if spec is None:
            self._logger.warning(
                "Model requested unknown tool '%s'.",
                call.name,
            )

            # Reporting the tools that actually exist - generically,
            # never any specific hardcoded name - lets the model
            # self-correct to a real tool on its next turn instead of
            # repeating (or hallucinating another) unknown name. This
            # is ordinary tool-calling protocol feedback (the same
            # "tool" role message used for every other tool result),
            # not a prompt or instruction: it only ever runs when the
            # model itself deviated from the tools it was offered.
            available = sorted(tools_by_name)

            return (
                json.dumps(
                    {
                        "error": f"Unknown tool '{call.name}'.",
                        "available_tools": available,
                    }
                ),
                None,
                False,
            )

        inputs = dict(call.arguments)
        execution_requirements = _extract_execution_requirements_override(inputs)

        content, succeeded = self._invoke_capability_through_brain(
            spec.capability_id,
            inputs,
            execution_requirements=execution_requirements,
        )

        return content, spec.capability_id, succeeded

    def _invoke_capability_through_brain(
        self,
        capability_id: str,
        inputs: dict[str, object],
        *,
        execution_requirements: Mapping[str, object] | None = None,
    ) -> tuple[str, bool]:
        """
        Invoke a capability through Brain and serialize the outcome
        into a JSON string suitable for a "tool" role message.

        Args:
            execution_requirements:
                Optional `Goal.metadata["execution_requirements"]`
                override, extracted from this call's own
                `model_selection_hint` argument (see
                `_extract_execution_requirements_override()`). `None`
                (the default, and every call before this parameter
                existed) builds the Goal with no `metadata` at all --
                fully backward compatible.
        """

        if self._brain is None:
            return (
                json.dumps(
                    {
                        "error": (
                            "Tool execution is unavailable: no Brain "
                            "is bound to the Ollama provider."
                        )
                    }
                ),
                False,
            )

        goal = Goal(
            id=f"tool-call-{capability_id}",
            capability_id=capability_id,
            inputs=inputs,
            metadata=(
                {"execution_requirements": execution_requirements}
                if execution_requirements is not None
                else {}
            ),
        )

        self._logger.debug("Executing tool: capability=%s", capability_id)

        try:
            brain_response = self._brain.handle(
                BrainRequest(goals=(goal,))
            )

        except Exception as ex:  # pragma: no cover - defensive
            self._logger.exception(
                "Unexpected error invoking capability '%s' through "
                "Brain.",
                capability_id,
            )
            self._logger.debug(
                "Tool finished: capability=%s succeeded=False", capability_id
            )
            return json.dumps({"error": str(ex)}), False

        if brain_response.planning_failure is not None:
            self._logger.debug(
                "Tool finished: capability=%s succeeded=False", capability_id
            )
            return (
                json.dumps({"error": str(brain_response.planning_failure)}),
                False,
            )

        if not brain_response.results:
            self._logger.debug(
                "Tool finished: capability=%s succeeded=False", capability_id
            )
            return json.dumps({"error": "Brain returned no result."}), False

        result = brain_response.results[0]

        if not result.succeeded:
            if result.failure is not None:
                message = str(result.failure)
            elif result.skip_reason is not None:
                message = result.skip_reason
            else:
                message = f"Capability '{capability_id}' did not succeed."

            self._logger.debug(
                "Tool finished: capability=%s succeeded=False", capability_id
            )
            return json.dumps({"error": message}), False

        payload = serialize_task_result(result.response)

        self._logger.debug(
            "Tool finished: capability=%s succeeded=True", capability_id
        )

        return json.dumps(payload, default=str), True
