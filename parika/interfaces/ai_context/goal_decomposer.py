"""
PARIKA AI Context Engineering - Goal Decomposer

Decomposes a high-level user request into multiple semantic Goals.
This is the missing layer that sits between user input and the
existing single-goal `chat.respond` pathway.

The decomposer uses the same LLM-based approach as StandardCodingAgent
but applies it generically to any user request, producing multiple
semantic Goals with proper dependencies.

This module owns ONLY goal decomposition. It never executes goals,
selects agents, or plans execution - those remain with Brain,
AgentOrchestrator, and Planner.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from parika.core.brain.context_engine import HeuristicTokenEstimator, TokenEstimator
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.planner.goal import Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.context_budget import resolve_runtime_context_budget
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.exceptions import (
    ProviderConnectionError, ProviderTimeoutError, ProviderRateLimitError,
    ProviderServerError, ProviderModelNotFoundError,
    ProviderAuthenticationError, ProviderAuthorizationError,
)
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.planner.model_selection.routing_config import RoutingConfig, load_routing_config
from parika.core.planner.model_selection.routing_strategy import select_fixed_routing_model
from parika.core.planner.model_selection.selector import select_provider_model
from parika.core.planner.model_selection.requirements import ExecutionRequirements, ThinkingMode, Requirement
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.tool_spec import ToolSpec
from parika.core.forensic_log import (
    get_current_trace_id,
    log_decomposer_input,
    log_decomposition_raw,
    log_decomposition_goals,
)


_PROMPT_TOKEN_ESTIMATOR: TokenEstimator = HeuristicTokenEstimator()
"""
Shared `TokenEstimator` used to measure the complete assembled decomposition
prompt -- the same `TokenEstimator` Protocol/default implementation Brain's
own Context Budgeting already uses (`parika.core.brain.context_engine`),
reused here rather than reimplemented.
"""


def _estimate_prompt_tokens(
    messages: tuple[ChatMessage, ...],
    *,
    estimator: TokenEstimator,
) -> int:
    """
    Estimate the complete, already-fully-assembled decomposition prompt's
    total token cost using `estimator` -- every message's role+content.

    GoalDecomposer does not advertise tools, so only messages are measured.
    """
    parts: list[str] = []

    for message in messages:
        parts.append(message.role)
        parts.append(message.content)

    return estimator.estimate("\n".join(parts))


def _get_all_enabled_capabilities(
    capability_registry: CapabilityRegistry,
) -> frozenset[str]:
    """Return all enabled capability IDs from the registry."""
    return frozenset(
        cap.id for cap in capability_registry.get_all()
        if cap.enabled
    )


_DECOMPOSITION_SYSTEM_PROMPT_TEMPLATE = """\
You are PARIKA's Goal Decomposer. Analyze the user's request and decompose it into independent semantic goals.

Available capability categories and their purposes:
- TOOL: External APIs, utilities, data access (weather, currency, web search, filesystem, shell, etc.)
- LLM: General conversation, reasoning, synthesis (chat.respond)
- VISION/OCR/IMAGE_GENERATION/VIDEO_GENERATION: Visual understanding and generation
- MEMORY/KNOWLEDGE: Long-term memory and knowledge retrieval
- SPEECH/TEXT_TO_SPEECH: Voice processing

Rules:
1. Each goal must target ONE specific capability (e.g., "weather.current", "currency.convert", "web.search")
2. Goals should be SEMANTIC objectives, not transport capabilities
3. chat.respond is for FINAL response synthesis ONLY - do not use it for data gathering
4. Identify dependencies: if goal B needs goal A's result, declare depends_on
5. Independent goals (no shared data) should have no dependencies
6. Simple requests (greeting, single fact) -> 1 goal
7. Complex requests -> multiple goals
8. CRITICAL: The FINAL chat.respond synthesis goal MUST depend on ALL data-gathering goals. If the user asks for multiple pieces of information (weather, currency, web search, etc.), create ONE final chat.respond goal that depends on ALL of them.

Respond with ONLY a JSON object matching this schema:
{{
  "goals": [
    {{"id": "goal_0", "capability_id": "weather.current", "inputs": {{"location": "Patna, Bihar"}}, "depends_on": []}},
    {{"id": "goal_1", "capability_id": "weather.forecast", "inputs": {{"location": "Patna, Bihar"}}, "depends_on": []}},
    {{"id": "goal_2", "capability_id": "currency.convert", "inputs": {{"from": "USD", "to": "INR", "amount": 1}}, "depends_on": []}},
    {{"id": "goal_3", "capability_id": "web.search", "inputs": {{"query": "Jharkhand protest outcome"}}, "depends_on": []}},
    {{"id": "goal_4", "capability_id": "chat.respond", "inputs": {{"message": "Summarize all results: weather, currency, and web search"}}, "depends_on": ["goal_0", "goal_1", "goal_2", "goal_3"]}}
  ]
}}

Available capabilities (enabled): {available_capabilities}

User request: {user_message}
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class DecompositionResult:
    """Result of goal decomposition."""
    goals: tuple[Goal, ...]
    """Decomposed goals ready for Brain"""
    raw_response: str
    """Raw LLM response for debugging"""
    successful_provider_id: str | None = None
    """Provider ID that successfully completed decomposition, if any"""
    successful_model_id: str | None = None
    """Model ID that successfully completed decomposition, if any"""


class DecompositionError(Exception):
    """Raised when goal decomposition fails."""
    pass


def _validate_decomposition(goals: list[Goal], user_message: str) -> None:
    """
    Validate that a decomposition meets the structural contract.
    
    A valid decomposition for a complex request MUST contain:
    - At least one data-gathering goal (non-chat.respond)
    - Exactly one synthesis goal (chat.respond) that depends on ALL data-gathering goals
    
    For simple requests, a single chat.respond goal without dependencies is valid.
    """
    if not goals:
        raise DecompositionError("Decomposition produced no goals")
    
    chat_respond_goals = [g for g in goals if g.capability_id == "chat.respond"]
    data_goals = [g for g in goals if g.capability_id != "chat.respond"]
    
    # Check for multiple chat.respond goals
    if len(chat_respond_goals) > 1:
        raise DecompositionError(f"Decomposition contains multiple chat.respond goals: {[g.id for g in chat_respond_goals]}")
    
    # If there are data goals, there MUST be a synthesis goal that depends on all of them
    if data_goals:
        if not chat_respond_goals:
            raise DecompositionError(
                f"Decomposition contains data-gathering goals { [g.id for g in data_goals] } "
                f"but no chat.respond synthesis goal. "
                f"Per the decomposition contract, a synthesis goal depending on all data goals is required."
            )
        
        synthesis_goal = chat_respond_goals[0]
        synthesis_deps = set(synthesis_goal.depends_on)
        data_goal_ids = {g.id for g in data_goals}
        
        if not synthesis_deps:
            raise DecompositionError(
                f"Synthesis goal {synthesis_goal.id} has no dependencies. "
                f"It must depend on all data-gathering goals: {sorted(data_goal_ids)}"
            )
        
        missing_deps = data_goal_ids - synthesis_deps
        if missing_deps:
            raise DecompositionError(
                f"Synthesis goal {synthesis_goal.id} missing dependencies on data goals: {sorted(missing_deps)}. "
                f"It must depend on ALL data-gathering goals: {sorted(data_goal_ids)}"
            )
        
        extra_deps = synthesis_deps - data_goal_ids
        if extra_deps:
            raise DecompositionError(
                f"Synthesis goal {synthesis_goal.id} depends on unknown goals: {sorted(extra_deps)}. "
                f"Valid data goal IDs: {sorted(data_goal_ids)}"
            )
    else:
        # No data goals - simple request, single chat.respond without deps is OK
        if len(chat_respond_goals) != 1:
            raise DecompositionError(f"Expected exactly one chat.respond goal for simple request, got {len(chat_respond_goals)}")
        if chat_respond_goals[0].depends_on:
            raise DecompositionError("Simple request chat.respond goal should not have dependencies")


class GoalDecomposer:
    """
    Decomposes user requests into multiple semantic Goals.
    
    Uses an LLM to analyze the request and produce a structured plan
    of goals with capabilities, inputs, and dependencies.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
        configuration: Configuration,
    ) -> None:
        self._capability_registry = capability_registry
        self._provider_manager = provider_manager
        self._configuration = configuration

    def decompose(
        self,
        user_message: str,
        *,
        available_capabilities: frozenset[str] | None = None,
    ) -> DecompositionResult:
        """
        Decompose a user message into multiple semantic Goals.
        
        Args:
            user_message: The user's natural language request
            available_capabilities: Optional filter of capability IDs to consider.
                                   Defaults to all enabled capabilities.
        
        Returns:
            DecompositionResult with goals and raw response
            
        Raises:
            DecompositionError: If decomposition fails after all attempts
        """
        # Use all enabled capabilities if not explicitly provided
        if available_capabilities is None:
            available_capabilities = _get_all_enabled_capabilities(
                self._capability_registry
            )

        # Build the decomposition prompt
        system_prompt = _DECOMPOSITION_SYSTEM_PROMPT_TEMPLATE.format(
            available_capabilities=sorted(available_capabilities),
            user_message=user_message,
        )

        messages = (
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_message),
        )

        # Get routing config to use its fixed_thinking setting for reasoning
        routing_config = load_routing_config(self._configuration)
        decomposition_reasoning = routing_config.fixed_thinking if routing_config.is_fixed else False

        # Get the routing model for decomposition
        routing_model = self._get_routing_model()
        if routing_model is None:
            raise DecompositionError(
                "No model available for goal decomposition. "
                "Ensure at least one provider with a text_generation model is configured and healthy."
            )
        
        # Unpack the tuple
        provider_id, model = routing_model

        # Estimate the assembled prompt tokens using the same TokenEstimator
        # infrastructure as the normal Planner path (goal_builder.py)
        estimated_prompt_tokens = _estimate_prompt_tokens(
            messages, estimator=_PROMPT_TOKEN_ESTIMATOR
        )

        # Resolve the Runtime Context Budget from the selected routing model's
        # limits and configuration -- same mechanism Planner uses for every
        # provider request. This yields the effective context window that
        # Ollama's driver will translate into `num_ctx`.
        context_budget = resolve_runtime_context_budget(
            model.limits,
            configuration=self._configuration,
            required_prompt_tokens=estimated_prompt_tokens,
        )

        # FORENSIC: Log decomposer input (after budget is computed for complete info)
        trace_id = get_current_trace_id()
        if trace_id:
            # Extract capability info
            all_caps = self._capability_registry.get_all()
            enabled_caps = [cap for cap in all_caps if cap.enabled]
            capability_ids = [cap.id for cap in enabled_caps]
            
            log_decomposer_input(
                trace_id=trace_id,
                model="goal_decomposition (routing model)",
                provider="routing_model",
                request_options={
                    "reasoning": decomposition_reasoning,
                    "temperature": 0.0,
                    "seed": 42,
                    "top_p": 1.0,
                    "context_window_tokens": context_budget.effective_context_window,
                    "estimated_prompt_tokens": estimated_prompt_tokens,
                },
                reasoning=decomposition_reasoning,
                temperature=0.0,
                seed=42,
                top_p=1.0,
                num_capabilities=len(capability_ids),
                capability_ids=capability_ids,
                system_prompt=system_prompt,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )

        # Execute decomposition via direct provider inference with retries
        max_retries = 2
        last_exception = None
        
        for attempt in range(max_retries + 1):
            chat_request = ChatRequest(
                messages=messages,
                options=RequestOptions(
                    reasoning=decomposition_reasoning,
                    temperature=0.0,
                    seed=42,
                    top_p=1.0,
                    context_window_tokens=context_budget.effective_context_window,
                    estimated_prompt_tokens=estimated_prompt_tokens,
                ),
            )

            try:
                response = self._provider_manager.execute(
                    provider_id=provider_id,
                    model=model,
                    request=chat_request,
                )
                
                # Extract the response text
                raw_response = self._extract_text_from_provider_response(response)
                
                # FORENSIC: Log raw decomposition output
                if trace_id:
                    log_decomposition_raw(
                        trace_id=trace_id,
                        raw_response=raw_response,
                    )

                goals = self._parse_decomposition(raw_response, available_capabilities, user_message)
                
                # Validate that decomposition contains a synthesis goal with dependencies
                _validate_decomposition(goals, user_message)
                
                # FORENSIC: Log decomposed goals
                if trace_id:
                    goal_list = []
                    for goal in goals:
                        goal_list.append({
                            "id": goal.id,
                            "capability_id": goal.capability_id,
                            "inputs": goal.inputs,
                            "depends_on": list(goal.depends_on),
                        })
                    log_decomposition_goals(
                        trace_id=trace_id,
                        goals=goal_list,
                    )

                return DecompositionResult(
                    goals=tuple(goals),
                    raw_response=raw_response,
                    successful_provider_id=provider_id,
                    successful_model_id=model.id,
                )
                
            except Exception as ex:
                last_exception = ex
                logger = logging.getLogger(__name__)
                logger.warning(f"Decomposition attempt {attempt + 1} failed: {ex}")
                if isinstance(ex, (ProviderConnectionError, ProviderTimeoutError,
                                   ProviderRateLimitError, ProviderServerError,
                                   ProviderModelNotFoundError,
                                   ProviderAuthenticationError, ProviderAuthorizationError)):
                    fallback = self._next_cloud_routing_model(provider_id, model, routing_config)
                    if fallback is not None:
                        provider_id, model = fallback
                        context_budget = resolve_runtime_context_budget(
                            model.limits, configuration=self._configuration,
                            required_prompt_tokens=estimated_prompt_tokens,
                        )
                        continue
                if attempt < max_retries:
                    continue
        
        # All attempts failed
        raise DecompositionError(
            f"Goal decomposition failed after {max_retries + 1} attempts: {last_exception}"
        ) from last_exception

    def _parse_decomposition(
        self,
        raw_response: str,
        available_capabilities: frozenset[str],
        user_message: str,
    ) -> list[Goal]:
        """Parse LLM response into Goal objects."""
        try:
            # First, try to parse the entire response as JSON directly.
            # This handles the common case where the LLM outputs raw JSON.
            try:
                data = json.loads(raw_response)
            except json.JSONDecodeError:
                # If that fails, try to extract JSON from a code block
                code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_response, re.DOTALL)
                if code_block_match:
                    json_str = code_block_match.group(1)
                    data = json.loads(json_str)
                else:
                    # Fallback: find balanced-brace JSON object using a stack-based approach
                    # This is more robust than regex for nested JSON
                    data = self._extract_balanced_json(raw_response)
                    if data is None:
                        raise ValueError("No valid JSON object found in response")
            
            goal_data_list = data.get("goals", [])
            
            if not goal_data_list:
                raise ValueError("No goals in decomposition")
            
            goals = []
            for i, goal_data in enumerate(goal_data_list):
                capability_id = goal_data.get("capability_id", "")
                
                # Validate capability exists
                if capability_id not in available_capabilities:
                    # Try to find a close match
                    capability_id = self._find_closest_capability(
                        capability_id, available_capabilities
                    )
                
                if capability_id not in available_capabilities:
                    continue  # Skip invalid capability
                
                goal_id = goal_data.get("id", f"goal_{i}")
                inputs = goal_data.get("inputs", {})
                depends_on = tuple(goal_data.get("depends_on", []))
                
                # For chat.respond, ensure it has the user message
                if capability_id == "chat.respond" and "message" not in inputs:
                    inputs["message"] = "Provide a comprehensive response based on the gathered information."
                
                goal = Goal(
                    id=goal_id,
                    capability_id=capability_id,
                    inputs=inputs,
                    depends_on=depends_on,
                )
                goals.append(goal)
            
            if not goals:
                raise ValueError("No valid goals after filtering")
            
            return goals
        
        except (json.JSONDecodeError, ValueError, KeyError) as ex:
            raise DecompositionError(f"Failed to parse decomposition response: {ex}") from ex
    
    def _extract_balanced_json(self, text: str) -> dict | None:
        """Extract the first complete JSON object using balanced brace matching."""
        # Find the first '{'
        start = text.find('{')
        if start == -1:
            return None
        
        # Use a stack to find the matching '}'
        brace_count = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    # Found the matching closing brace
                    json_str = text[start:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        return None
        
        return None

    def _find_closest_capability(
        self,
        requested: str,
        available: frozenset[str],
    ) -> str:
        """Find closest matching capability."""
        # Exact match
        if requested in available:
            return requested
        
        # Prefix match
        for cap in available:
            if cap.startswith(requested):
                return cap
        
        # Domain match
        domain = requested.split(".")[0] if "." in requested else requested
        for cap in available:
            if cap.startswith(f"{domain}."):
                return cap
        
        return requested  # Will be filtered out

    def _extract_text_from_provider_response(self, response) -> str:
        """Extract text from provider response."""
        if response is None:
            return ""
        
        # ChatResult IS the result (directly returned by provider.execute())
        if hasattr(response, "message"):  # ChatResult has .message
            return response.message.content
        
        # Fallback for legacy ProviderResponse with outputs dict
        result = response.outputs.get("result") if hasattr(response, 'outputs') and response.outputs else None
        if result is None:
            return ""
        
        if hasattr(result, "message"):
            return result.message.content
        return str(result)

    def _get_routing_model(self) -> tuple[str, ProviderModel] | None:
        """Get the routing model from configuration with fallback to automatic selection."""
        # Get routing config
        routing_config = load_routing_config(self._configuration)

        logger = logging.getLogger(__name__)
        logger.debug(
            "GoalDecomposer routing decision: "
            "routing_type=%s is_fixed=%s fixed_model_id=%s "
            "cloud_fixed_provider=%s cloud_fixed_model=%s "
            "cloud_fallback_provider=%s cloud_fallback_model=%s",
            routing_config.routing_type,
            routing_config.is_fixed,
            routing_config.fixed_model_id,
            routing_config.cloud_fixed_provider,
            routing_config.cloud_fixed_model,
            routing_config.cloud_fallback_provider,
            routing_config.cloud_fallback_model,
        )

        if routing_config.routing_type == "cloud":
            providers = {p.id: p for p in self._provider_manager.get_all()}
            candidates = (
                (routing_config.cloud_fixed_provider, routing_config.cloud_fixed_model),
                (routing_config.cloud_fallback_provider, routing_config.cloud_fallback_model),
                (routing_config.fixed_provider_id, routing_config.fixed_model_id),
            )
            for provider_id, model_id in candidates:
                if not provider_id or not model_id or provider_id not in providers:
                    continue
                for model in providers[provider_id].models:
                    if model.id == model_id:
                        logger.debug("GoalDecomposer routing branch=cloud provider=%s model=%s", provider_id, model.id)
                        return provider_id, model
            logger.warning("Configured cloud routing chain unavailable; using local/automatic routing")

        if not routing_config.is_fixed:
            # For non-fixed mode, we would need to use the full model selection
            # For now, only support fixed mode as per current config
            return None
        
        # Get all providers
        providers = self._provider_manager.get_all()
        
        # Create minimal execution requirements for routing model
        requirements = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            tool_calling=Requirement.NOT_NEEDED,
            streaming_required=False,
            required_modalities=frozenset(["text"]),
        )
        
        # Try fixed routing model first
        selection_result = select_fixed_routing_model(
            providers=providers,
            requirements=requirements,
            routing_config=routing_config,
            logger=logging.getLogger(__name__),
        )
        
        if selection_result is not None and selection_result.selected_model is not None:
            return (selection_result.selected_provider_id, selection_result.selected_model)
        
        # Fixed model not available - fall back to automatic model selection
        logger = logging.getLogger(__name__)
        logger.info("Fixed routing model unavailable, falling back to automatic model selection for decomposition")
        
        # Use the standard model selector for decomposition
        from parika.core.planner.model_selection.config import load_model_selection_config
        from parika.core.planner.model_selection import DEFAULT_SCORING_RULES
        
        model_selection_config = load_model_selection_config(self._configuration)
        
        auto_selection = select_provider_model(
            providers=providers,
            requirements=requirements,
            config=model_selection_config,
            rules=DEFAULT_SCORING_RULES,
            logger=logger,
        )
        
        if auto_selection.succeeded and auto_selection.selected_model is not None:
            logger.info(f"Using automatic routing model: provider={auto_selection.selected_provider_id} model={auto_selection.selected_model.id}")
            return (auto_selection.selected_provider_id, auto_selection.selected_model)
        
        return None

    def _next_cloud_routing_model(self, current_provider_id, current_model, routing_config):
        if routing_config.routing_type != "cloud":
            return None
        targets = ((routing_config.cloud_fallback_provider, routing_config.cloud_fallback_model),
                   (routing_config.fixed_provider_id, routing_config.fixed_model_id))
        providers = {p.id: p for p in self._provider_manager.get_all()}
        for pid, mid in targets:
            if not mid or pid == current_provider_id and mid == current_model.id:
                continue
            if pid is not None:
                # Specific provider requested - must exist in registry
                provider = providers.get(pid)
                if provider is None:
                    continue
                models = iter(provider.models)
            else:
                # No specific provider - search all providers
                models = (m for p in providers.values() for m in p.models)
            for candidate in models:
                if candidate.id == mid:
                    owner = pid or next(p.id for p in providers.values() if candidate in p.models)
                    return owner, candidate
        return None
        
        logger.warning("No model available for goal decomposition")
        return None


def create_goal_decomposer(
    *,
    capability_registry: CapabilityRegistry,
    provider_manager: ProviderManager,
    configuration: Configuration,
) -> GoalDecomposer:
    """Factory function to create a GoalDecomposer."""
    return GoalDecomposer(
        capability_registry=capability_registry,
        provider_manager=provider_manager,
        configuration=configuration,
    )
