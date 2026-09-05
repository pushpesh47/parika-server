"""
PARIKA Planner

Provides the core component responsible for transforming user goals
into executable plans.

Planner accepts already-decomposed Goal objects (semantic goal
decomposition using AI reasoning belongs to Brain), orders them
according to their declared dependencies, evaluates any supplied
PolicyRule instances against resource-aware context, selects an
execution backend and target for each goal (Tool or Provider model),
and produces an immutable, dependency-ordered ExecutionPlan of
CapabilityExecutionRequest instances.

Planner does not execute tasks. It never invokes TaskManager,
CapabilityExecutor, ToolManager, or ProviderManager execution methods.
Planner also does not route requests; selecting the runtime dispatch
path for a request belongs to Router.
"""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any
from uuid import uuid4

from parika.core.capability_executor.execution_backend import (
    ExecutionBackend,
)
from parika.core.capability_executor.execution_target import (
    ExecutionTarget,
)
from parika.core.capability_executor.request import (
    CapabilityExecutionRequest,
)
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_resolver.capability_request import (
    CapabilityRequest,
)
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.logger.logger import Logger
from parika.core.policy_engine.policy_effect import PolicyEffect
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.policy_engine.request import PolicyEvaluationRequest
from parika.core.provider_manager.context_budget import (
    resolve_runtime_context_budget,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager

from .exceptions import (
    CyclicDependencyError,
    DuplicateGoalIdError,
    GoalDeniedByPolicyError,
    InvalidGoalError,
    MissingProviderRequestBuilderError,
    NoAvailableProviderModelError,
    NoAvailableToolError,
    UnknownGoalDependencyError,
)
from .execution_plan import ExecutionPlan
from .goal import (
    ROUTING_GOAL_METADATA_KEY,
    TERMINAL_SYNTHESIS_GOAL_METADATA_KEY,
    Goal,
)
from .model_selection import (
    DEFAULT_SCORING_RULES,
    ExperienceRule,
    ExperienceSource,
    ScoringRule,
    apply_context_budget,
    apply_reasoning_preference,
    build_execution_requirements,
    load_model_selection_config,
    load_routing_config,
    read_estimated_prompt_tokens,
    select_fixed_routing_model,
    select_provider_model,
)
from .plan_step import PlanStep

CATEGORY_TO_MODEL_CAPABILITY: dict[CapabilityCategory, ModelCapability] = {
    CapabilityCategory.LLM: ModelCapability.TEXT_GENERATION,
    CapabilityCategory.REASONING: ModelCapability.REASONING,
    CapabilityCategory.VISION: ModelCapability.VISION,
    CapabilityCategory.OCR: ModelCapability.VISION,
    CapabilityCategory.EMBEDDING: ModelCapability.EMBEDDING,
    CapabilityCategory.TRANSLATION: ModelCapability.TRANSLATION,
    CapabilityCategory.SPEECH: ModelCapability.SPEECH_TO_TEXT,
    CapabilityCategory.TEXT_TO_SPEECH: ModelCapability.TEXT_TO_SPEECH,
    CapabilityCategory.IMAGE_GENERATION: ModelCapability.IMAGE_GENERATION,
    CapabilityCategory.VIDEO_GENERATION: ModelCapability.VIDEO_GENERATION,
}
"""
Maps a CapabilityCategory to the ModelCapability required from a
ProviderModel when a goal in that category is routed to the PROVIDER
execution backend.

Categories not present in this mapping (including TOOL, which is
always routed to ToolManager) cannot be satisfied by a Provider.

`TEXT_TO_SPEECH` is a distinct category from `SPEECH` (which requires
`SPEECH_TO_TEXT`) for the same reason `IMAGE_GENERATION`/
`VIDEO_GENERATION` are distinct from `VISION`: a category maps to
exactly one hard-required `ModelCapability`, so speech *recognition*
(understanding, like VISION/OCR) and speech *synthesis* (generation,
like IMAGE_GENERATION/VIDEO_GENERATION) cannot share one category
without incorrectly requiring every candidate model to support both
directions at once.
"""


def _default_scoring_rules(
    experience_source: ExperienceSource | None,
) -> tuple[ScoringRule, ...]:
    """
    Return `DEFAULT_SCORING_RULES`, rebuilding its `ExperienceRule`
    with `experience_source` when one is supplied. Returns
    `DEFAULT_SCORING_RULES` unchanged when `experience_source` is
    `None`, so behavior is identical to before this parameter existed.
    """

    if experience_source is None:
        return DEFAULT_SCORING_RULES

    return tuple(
        ExperienceRule(experience_source)
        if isinstance(rule, ExperienceRule)
        else rule
        for rule in DEFAULT_SCORING_RULES
    )


class Planner:
    """
    Transforms Goals into an executable, dependency-ordered
    ExecutionPlan.

    Planner performs dependency ordering across the supplied Goals,
    evaluates any policy rules attached to each Goal, and determines
    the execution strategy (execution backend, Tool, or Provider
    model) for each Goal. The result is an immutable ExecutionPlan of
    CapabilityExecutionRequest instances ready for TaskManager and
    CapabilityExecutor.

    Planner intentionally does not:

    - Execute tasks. It never invokes execution methods on
      TaskManager, CapabilityExecutor, ToolManager, or
      ProviderManager.
    - Route requests. Selecting the runtime dispatch path for a
      request belongs to Router.
    """

    def __init__(
        self,
        *,
        capability_resolver: CapabilityResolver,
        resource_manager: ResourceManager,
        policy_engine: PolicyEngine,
        provider_manager: ProviderManager,
        tool_manager: ToolManager,
        logger: Logger,
        configuration: Configuration | None = None,
        scoring_rules: Sequence[ScoringRule] | None = None,
        experience_source: ExperienceSource | None = None,
    ) -> None:
        """
        Initialize the Planner.

        Args:
            capability_resolver:
                Resolves each goal's capability identifier.

            resource_manager:
                Supplies the resource snapshot made available to
                policy evaluation.

            policy_engine:
                Evaluates each goal's supplied PolicyRule instances.

            provider_manager:
                Supplies Provider and ProviderModel candidates for
                goals routed to the PROVIDER execution backend.

            tool_manager:
                Supplies Tool candidates for goals routed to the TOOL
                execution backend.

            logger:
                PARIKA Logger component.

            configuration:
                Optional Configuration, used to read `[model_selection]`
                (see `model_selection/config.py`) and `[routing_model]`
                (see `model_selection/routing_config.py`). Omitting it
                still works, using built-in default weights/preferences
                and `[routing_model] mode = "auto"`.

            scoring_rules:
                Optional override of the `ScoringRule` sequence used to
                score PROVIDER candidates. Defaults to
                `model_selection.DEFAULT_SCORING_RULES`.

            experience_source:
                Optional `ExperienceSource` (a structurally-typed
                Protocol Planner owns -- see
                `model_selection/experience_source.py`). When supplied
                and `scoring_rules` is not explicitly overridden, the
                default `ExperienceRule` is rebuilt with this source so
                it can contribute a real historical-success-rate
                signal; its `[model_selection.weights] experience`
                weight defaults to `0.0` (opt-in) regardless. Planner
                never imports a concrete implementation -- see
                docs/architecture/Intelligence_Foundation_Design.md
                section 6A.
        """

        self._capability_resolver = capability_resolver
        self._resource_manager = resource_manager
        self._policy_engine = policy_engine
        self._provider_manager = provider_manager
        self._tool_manager = tool_manager
        self._logger = logger.get_logger(__name__)
        self._configuration = configuration

        self._model_selection_config = load_model_selection_config(
            configuration
        )
        self._routing_config = load_routing_config(configuration)
        self._scoring_rules = (
            tuple(scoring_rules)
            if scoring_rules is not None
            else _default_scoring_rules(experience_source)
        )

    def plan(self, goals: Sequence[Goal]) -> ExecutionPlan:
        """
        Produce an ExecutionPlan from a collection of Goals.

        Args:
            goals:
                Goals to plan. Each Goal's `depends_on` must reference
                only other Goal identifiers present in this same
                sequence.

        Returns:
            An immutable, dependency-ordered ExecutionPlan.

        Raises:
            InvalidGoalError:
                If `goals` contains a non-Goal object, or is empty.

            DuplicateGoalIdError:
                If two Goals share the same identifier.

            UnknownGoalDependencyError:
                If a Goal depends on an identifier not present in
                `goals`.

            CyclicDependencyError:
                If Goal dependencies form a cycle.

            GoalDeniedByPolicyError:
                If PolicyEngine denies a Goal.

            NoAvailableToolError:
                If a TOOL-category Goal has no matching enabled Tool.

            NoAvailableProviderModelError:
                If a Goal cannot be satisfied by any enabled Provider
                model.

            MissingProviderRequestBuilderError:
                If a Goal routed to the PROVIDER backend does not
                supply a provider_request_builder.
        """

        started_at = perf_counter()

        self._validate_goals(goals)

        ordered_goals = self._order_by_dependency(goals)

        resource_snapshot = self._resource_manager.get_resource_snapshot()

        steps: list[PlanStep] = []

        for goal in ordered_goals:
            step = self._plan_goal(goal, resource_snapshot=resource_snapshot)
            steps.append(step)

        plan = ExecutionPlan(id=uuid4().hex, steps=tuple(steps))

        self._logger.debug(
            "Produced execution plan '%s' with %d step(s): %s "
            "(planning_duration_ms=%.3f).",
            plan.id,
            len(plan.steps),
            [
                (
                    step.goal_id,
                    step.execution_request.resolution.definition.id,
                    step.execution_request.target.backend.value,
                )
                for step in plan.steps
            ],
            (perf_counter() - started_at) * 1000,
        )

        return plan

    # ------------------------------------------------------------------
    # Goal Decomposition Support
    # ------------------------------------------------------------------

    def _validate_goals(self, goals: Sequence[Goal]) -> None:
        """
        Validate the structural integrity of a collection of Goals.

        Raises:
            InvalidGoalError:
                If `goals` is empty or contains a non-Goal object.

            DuplicateGoalIdError:
                If two Goals share the same identifier.

            UnknownGoalDependencyError:
                If a Goal depends on an unknown identifier.
        """

        if not goals:
            raise InvalidGoalError("At least one Goal is required.")

        seen_ids: set[str] = set()

        for goal in goals:

            if not isinstance(goal, Goal):
                raise InvalidGoalError("Expected a Goal instance.")

            if goal.id in seen_ids:
                raise DuplicateGoalIdError(
                    f"Duplicate goal identifier '{goal.id}'."
                )

            seen_ids.add(goal.id)

        for goal in goals:
            for dependency_id in goal.depends_on:
                if dependency_id not in seen_ids:
                    raise UnknownGoalDependencyError(
                        f"Goal '{goal.id}' depends on unknown goal "
                        f"'{dependency_id}'."
                    )

    def _order_by_dependency(
        self,
        goals: Sequence[Goal],
    ) -> list[Goal]:
        """
        Topologically sort Goals so that every Goal appears after
        every Goal it depends on.

        Raises:
            CyclicDependencyError:
                If Goal dependencies form a cycle.
        """

        goals_by_id = {goal.id: goal for goal in goals}
        remaining_dependencies = {
            goal.id: set(goal.depends_on) for goal in goals
        }

        ordered: list[Goal] = []
        resolved_ids: set[str] = set()

        while remaining_dependencies:

            ready_ids = sorted(
                goal_id
                for goal_id, dependencies in remaining_dependencies.items()
                if dependencies <= resolved_ids
            )

            if not ready_ids:
                raise CyclicDependencyError(
                    "Goal dependencies contain a cycle: "
                    f"{sorted(remaining_dependencies)}."
                )

            for goal_id in ready_ids:
                ordered.append(goals_by_id[goal_id])
                resolved_ids.add(goal_id)
                del remaining_dependencies[goal_id]

        return ordered

    # ------------------------------------------------------------------
    # Execution Strategy
    # ------------------------------------------------------------------

    def _plan_goal(
        self,
        goal: Goal,
        *,
        resource_snapshot: Any,
    ) -> PlanStep:
        """
        Produce a single PlanStep from a Goal.
        """

        resolution = self._capability_resolver.resolve(
            CapabilityRequest(
                capability_id=goal.capability_id,
                metadata=goal.metadata,  # type: ignore[arg-type]
            )
        )

        self._enforce_policy(goal, resolution, resource_snapshot)

        target, backend_request = self._select_execution_strategy(
            goal,
            resolution,
            resource_snapshot,
        )

        execution_request = CapabilityExecutionRequest(
            resolution=resolution,
            target=target,
            backend_request=backend_request,
            metadata=goal.metadata,
        )

        return PlanStep(
            goal_id=goal.id,
            execution_request=execution_request,
            depends_on=goal.depends_on,
        )

    def _enforce_policy(
        self,
        goal: Goal,
        resolution: CapabilityResolution,
        resource_snapshot: Any,
    ) -> None:
        """
        Evaluate a Goal's supplied PolicyRule instances.

        Raises:
            GoalDeniedByPolicyError:
                If PolicyEngine denies the goal.
        """

        request = PolicyEvaluationRequest(
            rules=goal.policy_rules,
            context={
                "goal_id": goal.id,
                "capability_id": goal.capability_id,
                "capability_category": resolution.definition.category,
                "inputs": goal.inputs,
                "resource_snapshot": resource_snapshot,
            },
            default_effect=PolicyEffect.ALLOW,
        )

        decision = self._policy_engine.evaluate(request)

        if not decision.is_allowed:
            raise GoalDeniedByPolicyError(
                f"Goal '{goal.id}' was denied by policy "
                f"'{decision.matched_rule_id}': {decision.reason}"
            )

    def _select_execution_strategy(
        self,
        goal: Goal,
        resolution: CapabilityResolution,
        resource_snapshot: Any = None,
    ) -> tuple[ExecutionTarget, ToolRequest | Any]:
        """
        Select the execution backend and target for a resolved Goal.

        Returns:
            A tuple of (ExecutionTarget, backend_request).
        """

        category = resolution.definition.category

        if category is CapabilityCategory.TOOL:
            return self._select_tool(goal)

        return self._select_provider_model(
            goal, resolution, category, resource_snapshot
        )

    def _select_tool(
        self,
        goal: Goal,
    ) -> tuple[ExecutionTarget, ToolRequest]:
        """
        Select an enabled Tool implementing the goal's capability.

        Raises:
            NoAvailableToolError:
                If no enabled Tool implements the capability.
        """

        candidates = sorted(
            (
                tool
                for tool in self._tool_manager.get_all()
                if tool.enabled and goal.capability_id in tool.capabilities
            ),
            key=lambda tool: tool.id,
        )

        if not candidates:
            raise NoAvailableToolError(
                f"No enabled Tool implements capability "
                f"'{goal.capability_id}'."
            )

        tool: Tool = candidates[0]

        target = ExecutionTarget(
            backend=ExecutionBackend.TOOL,
            identifier=tool.id,
        )

        backend_request = ToolRequest(
            arguments=goal.inputs,
            metadata=goal.metadata,
        )

        return target, backend_request

    def _select_provider_model(
        self,
        goal: Goal,
        resolution: CapabilityResolution,
        category: CapabilityCategory,
        resource_snapshot: Any = None,
    ) -> tuple[ExecutionTarget, Any]:
        """
        Select an enabled Provider and ProviderModel satisfying the
        goal's capability category.

        Delegates to `model_selection.select_provider_model()`: builds
        the provider-independent `ExecutionRequirements` for this goal
        and evaluates every registered Provider's models against them.
        Selection remains exclusively Planner's responsibility;
        ProviderManager is only ever read from (`get_all()`).

        `resource_snapshot`, already computed once per `plan()` call,
        is forwarded unchanged into `ExecutionRequirements
        .available_resources` so the Model Selection Framework's
        resource-validation filtering step (`model_selection.filtering
        ._filter_resources`) can consult it; `None` simply skips that
        step, exactly as before this parameter existed.

        Once a model is selected, also computes this request's
        Runtime Context Budget (`provider_manager.context_budget
        .resolve_runtime_context_budget()`) from the selected model's
        own advertised `ModelLimits.context_window` (the single
        source of truth) narrowed by `[context_engine]` configuration
        and grown, when needed, to cover the complete assembled
        prompt's own measured size -- read via
        `read_estimated_prompt_tokens()` from the built
        `ProviderRequest`'s generic `options.estimated_prompt_tokens`
        field, already set by AI Context Engineering's Prompt
        Engineering responsibility (`interfaces/ai_context
        /goal_builder.py`) when it built `backend_request` just above.
        Planner never measures a prompt itself; it only ever reads an
        already-supplied, provider-independent token count. The
        result is applied onto the built `ProviderRequest`'s generic
        `options.context_window_tokens` field via
        `apply_context_budget()` -- exactly like the existing
        `RequestOptions.reasoning` preference injection below.
        Translating that budget into a concrete provider-specific
        context parameter (e.g. Ollama's `num_ctx`) is left entirely
        to the Provider.

        When this Goal is the *routing* Goal (`Goal.metadata
        [ROUTING_GOAL_METADATA_KEY]` is `True` -- set only by
        `interfaces/ai_context/goal_builder.build_chat_goal()`) and
        `[routing_model] mode = "fixed"`, selection is instead
        resolved directly by `model_selection.select_fixed_routing_model()`,
        skipping scoring entirely for this one decision (see
        `docs/architecture/Model_Selection_Framework.md` §14). Worker
        Goals never set that metadata key, so this never affects
        worker model selection, and a configured model that turns out
        to be unavailable falls back to the exact same
        `select_provider_model()` call below, with a WARNING already
        logged - never a crash.

        Raises:
            NoAvailableProviderModelError:
                If no enabled Provider exposes a matching Model.

            MissingProviderRequestBuilderError:
                If the goal does not supply a provider_request_builder.
        """

        required_capability = CATEGORY_TO_MODEL_CAPABILITY.get(category)

        if required_capability is None:
            raise NoAvailableProviderModelError(
                f"Capability category '{category.value}' cannot be "
                "satisfied by a Provider model."
            )

        requirements = build_execution_requirements(
            capability=required_capability,
            category=category,
            capability_id=goal.capability_id,
            goal_metadata=goal.metadata,
            goal_inputs=goal.inputs,
            available_resources=resource_snapshot,
        )

        self._logger.debug(
            "Planner passing requirements to selector: "
            "capability=%s "
            "task_category=%s "
            "specializations=%s",
            requirements.capability.value,
            requirements.task_category,
            sorted(requirements.required_specializations),
        )

        selection = None

        is_routing_or_synthesis = (
            goal.metadata.get(ROUTING_GOAL_METADATA_KEY) is True
            or goal.metadata.get(TERMINAL_SYNTHESIS_GOAL_METADATA_KEY) is True
        )

        if self._routing_config.is_fixed and is_routing_or_synthesis:
            self._logger.debug(
                "Planner routing decision: "
                "routing_type=%s is_fixed=%s fixed_model_id=%s "
                "cloud_fixed_provider=%s cloud_fixed_model=%s "
                "cloud_fallback_provider=%s cloud_fallback_model=%s",
                self._routing_config.routing_type,
                self._routing_config.is_fixed,
                self._routing_config.fixed_model_id,
                self._routing_config.cloud_fixed_provider,
                self._routing_config.cloud_fixed_model,
                self._routing_config.cloud_fallback_provider,
                self._routing_config.cloud_fallback_model,
            )

            if self._routing_config.routing_type == "cloud":
                selection = self._select_cloud_routing_model(
                    providers=self._provider_manager.get_all(),
                    requirements=requirements,
                    goal=goal,
                )

            if selection is None:
                self._logger.debug("Planner routing branch=local_fixed")
                selection = select_fixed_routing_model(
                    providers=self._provider_manager.get_all(),
                    requirements=requirements,
                    routing_config=self._routing_config,
                    logger=self._logger,
                )
            else:
                self._logger.debug("Planner routing branch=cloud")

        if selection is None:
            selection = select_provider_model(
                providers=self._provider_manager.get_all(),
                requirements=requirements,
                config=self._model_selection_config,
                rules=self._scoring_rules,
                logger=self._logger,
            )

        if not selection.succeeded:
            raise NoAvailableProviderModelError(
                f"No enabled Provider exposes a Model supporting "
                f"'{required_capability.value}' for capability "
                f"'{goal.capability_id}' ({selection.reason})."
            )

        self._logger.debug(
            "Planner selection model: "
            "model=%s "
            "provider=%s",
            selection.selected_model.name if selection.selected_model else "None",
            selection.selected_provider_id,
        )
        model = selection.selected_model
        provider_id = selection.selected_provider_id
        assert model is not None and provider_id is not None  # narrowed by `selection.succeeded`

        if goal.provider_request_builder is None:
            raise MissingProviderRequestBuilderError(
                f"Goal '{goal.id}' requires a provider_request_builder "
                "to invoke a PROVIDER execution backend."
            )

        backend_request = goal.provider_request_builder(resolution, model)
        backend_request = apply_reasoning_preference(
            backend_request, selection.reasoning_enabled
        )

        required_prompt_tokens = read_estimated_prompt_tokens(backend_request)

        context_budget = resolve_runtime_context_budget(
            model.limits,
            configuration=self._configuration,
            required_prompt_tokens=required_prompt_tokens,
        )
        backend_request = apply_context_budget(backend_request, context_budget)

        if (
            required_prompt_tokens is not None
            and required_prompt_tokens > 0
            and context_budget.prompt_budget < required_prompt_tokens
        ):
            self._logger.warning(
                "Goal '%s': the assembled prompt (~%d tokens) exceeds "
                "model '%s's own advertised context window even after "
                "growing the Runtime Context Budget to %d tokens; the "
                "model's own context window is a hard limit that "
                "cannot be exceeded, so the Provider may still need to "
                "truncate this request.",
                goal.id,
                required_prompt_tokens,
                model.id,
                context_budget.effective_context_window,
            )

        target = ExecutionTarget(
            backend=ExecutionBackend.PROVIDER,
            identifier=provider_id,
            model=model,
        )

        return target, backend_request

    def _select_cloud_routing_model(
        self,
        *,
        providers,
        requirements,
        goal: Goal | None = None,
    ):
        """
        Select a cloud routing model based on cloud configuration.

        Tries cloud primary, then cloud fallback, then local fixed model.
        Returns None if no cloud model is available.
        
        If the goal has preferred_synthesis_provider_id and
        preferred_synthesis_model_id in its metadata (set by the AI Context
        layer when goal decomposition succeeded with that provider/model),
        that provider/model is tried FIRST before the configured chain.
        """
        routing_config = self._routing_config
        logger = self._logger

        # FIRST: Check if there's a preferred provider/model from successful
        # goal decomposition (request-scoped preference)
        if goal is not None:
            preferred_provider_id = goal.metadata.get("preferred_synthesis_provider_id")
            preferred_model_id = goal.metadata.get("preferred_synthesis_model_id")
            if preferred_provider_id and preferred_model_id:
                for provider in providers:
                    if provider.id == preferred_provider_id:
                        for model in provider.models:
                            if model.id == preferred_model_id:
                                logger.debug(
                                    "Using preferred synthesis provider from decomposition: provider=%s model=%s",
                                    provider.id,
                                    model.id,
                                )
                                return self._create_selection_result(
                                    provider=provider,
                                    model=model,
                                    requirements=requirements,
                                    reason=f"preferred synthesis provider from successful decomposition provider='{provider.id}' model='{model.id}'",
                                    skip_health_check=True,
                                )

        # Try cloud primary
        if routing_config.cloud_fixed_provider and routing_config.cloud_fixed_model:
            for provider in providers:
                if provider.id == routing_config.cloud_fixed_provider:
                    for model in provider.models:
                        if model.id == routing_config.cloud_fixed_model:
                            logger.debug(
                                "Using cloud primary routing model: provider=%s model=%s",
                                provider.id,
                                model.id,
                            )
                            return self._create_selection_result(
                                provider=provider,
                                model=model,
                                requirements=requirements,
                                reason=f"cloud primary routing model configured via [routing.cloud_model] fixed_provider='{provider.id}' fixed_model='{model.id}'",
                                skip_health_check=True,
                            )

        # Try cloud fallback
        if routing_config.cloud_fallback_provider and routing_config.cloud_fallback_model:
            for provider in providers:
                if provider.id == routing_config.cloud_fallback_provider:
                    for model in provider.models:
                        if model.id == routing_config.cloud_fallback_model:
                            logger.debug(
                                "Using cloud fallback routing model: provider=%s model=%s",
                                provider.id,
                                model.id,
                            )
                            return self._create_selection_result(
                                provider=provider,
                                model=model,
                                requirements=requirements,
                                reason=f"cloud fallback routing model configured via [routing.cloud_model] fallback_provider='{provider.id}' fallback_model='{model.id}'",
                                skip_health_check=True,
                            )

        # Try local fixed model as last resort
        if routing_config.fixed_provider_id and routing_config.fixed_model_id:
            for provider in providers:
                if provider.id == routing_config.fixed_provider_id:
                    for model in provider.models:
                        if model.id == routing_config.fixed_model_id:
                            logger.debug(
                                "Using local fixed routing model as cloud fallback: provider=%s model=%s",
                                provider.id,
                                model.id,
                            )
                            return self._create_selection_result(
                                provider=provider,
                                model=model,
                                requirements=requirements,
                                reason=f"local fixed routing model (cloud fallback) configured via [routing_model] fixed_model='{provider.id}/{model.id}'",
                                skip_health_check=True,
                            )

        return None

    def _create_selection_result(self, *, provider, model, requirements, reason, skip_health_check=False):
        """Create a ModelSelectionResult for a directly selected model."""
        from parika.core.planner.model_selection.filtering import evaluate_hard_requirements
        from parika.core.planner.model_selection.requirements import ThinkingMode
        from parika.core.planner.model_selection.selection_result import ModelSelectionResult

        if not skip_health_check:
            rejection_reason = evaluate_hard_requirements(provider, model, requirements)
            if rejection_reason is not None:
                self._logger.debug(
                    "Model %s/%s rejected by hard requirements: %s",
                    provider.id,
                    model.id,
                    rejection_reason,
                )
                return None

        reasoning_enabled = bool(self._routing_config.fixed_thinking)
        thinking_mode = ThinkingMode.ON if reasoning_enabled else ThinkingMode.OFF

        return ModelSelectionResult(
            requirements=requirements,
            selected_provider_id=provider.id,
            selected_model=model,
            thinking_mode=thinking_mode,
            reasoning_enabled=reasoning_enabled,
            total_score=None,
            breakdown=(),
            reason=reason,
            evaluated_candidates=(),
        )
