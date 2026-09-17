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
from parika.core.autonomous.execution_mode import ExecutionMode
from parika.core.forensic_log import (
    get_current_trace_id,
    log_decomposer_input,
    log_decomposition_provider_failure,
    log_decomposition_raw,
    log_decomposition_goals,
    log_generic,
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

def _build_capability_schemas(
    capability_registry: CapabilityRegistry,
    available_capabilities: frozenset[str],
) -> dict[str, dict[str, Any]]:
    """
    Build a mapping of capability_id -> parameter schema for all available capabilities.

    Extracts the existing `metadata["tool_affordance"]["parameters"]` from each
    CapabilityDefinition. This is the same source of truth used by
    `tool_context.py` when building ToolSpec for native tool calling.
    """
    schemas: dict[str, dict[str, Any]] = {}

    for cap_id in available_capabilities:
        try:
            definition = capability_registry.get(cap_id)
        except Exception:
            continue

        affordance = definition.metadata.get("tool_affordance")
        if not isinstance(affordance, dict):
            continue

        parameters = affordance.get("parameters")
        if not isinstance(parameters, dict):
            continue

        schemas[cap_id] = parameters

    return schemas


def _format_capability_schemas_for_prompt(
    schemas: dict[str, dict[str, Any]],
) -> str:
    """Format capability parameter schemas for inclusion in the decomposition prompt."""
    if not schemas:
        return "  (no parameter schemas available)"

    lines = []
    for cap_id, schema in sorted(schemas.items()):
        lines.append(f"  {cap_id}:")
        schema_type = schema.get("type", "object")
        lines.append(f"    type: {schema_type}")

        properties = schema.get("properties", {})
        if properties:
            lines.append("    properties:")
            for prop_name, prop_schema in sorted(properties.items()):
                prop_type = prop_schema.get("type", "any")
                prop_desc = prop_schema.get("description", "")
                desc_str = f" - {prop_desc}" if prop_desc else ""
                lines.append(f"      {prop_name}: {prop_type}{desc_str}")

        required = schema.get("required", [])
        if required:
            lines.append(f"    required: {', '.join(sorted(required))}")

    return "\n".join(lines)


_DECOMPOSITION_SYSTEM_PROMPT_TEMPLATE = """\
You are PARIKA's Goal Decomposer. Analyze the user's request and decompose it into semantic execution goals ending with one final user-facing response.

Available capability categories and their purposes:
- TOOL: External APIs, utilities, data access (weather, currency, web search, filesystem, shell, etc.)
- LLM: General conversation, reasoning, synthesis (chat.respond)
- VISION/OCR/IMAGE_GENERATION/VIDEO_GENERATION: Visual understanding and generation
- MEMORY/KNOWLEDGE: Long-term memory and knowledge retrieval
- SPEECH/TEXT_TO_SPEECH: Voice processing

Rules:
1. Each goal must target ONE specific capability (e.g., "weather.current", "currency.convert", "web.search", "image.generate")
2. Goals should be SEMANTIC objectives, not transport capabilities
3. chat.respond is for FINAL response synthesis ONLY - do not use it for data gathering
4. Identify dependencies: if goal B needs goal A's result, declare depends_on
5. Independent non-synthesis goals should have no dependencies
6. Simple requests (greeting, single fact) -> 1 chat.respond goal
7. Complex requests -> multiple execution goals followed by chat.respond
8. CRITICAL: Every request MUST produce exactly one final chat.respond goal. chat.respond MUST be the last goal and MUST be the final user-facing response/synthesis step.
9. The final chat.respond goal MUST depend on ALL preceding goals. If there are no preceding goals, chat.respond has no dependencies.
10. Terminal capabilities (image.generate, video.generate, voice.text_to_speech, media actions, filesystem.write, coding.execute_task, etc.) perform the requested action, but MUST still be followed by chat.respond so PARIKA can report the result to the user.
11. DEPENDENCY REFERENCE SYNTAX: When goal B depends on goal A and needs a value from goal A's result, goal B MUST use the formal reference syntax in its inputs:
    - Use {{goal_A.result.<field>}} to reference a field from goal A's result
    - Use {{goal_A.result.matches[0]}} to reference the first element of a list
    - Use {{goal_A.result.some.nested.path}} for nested fields
    - Do NOT use natural language placeholders like "<Parika project directory identified by goal_0>"
    - The referenced goal ID MUST match the dependency declared in depends_on
    - The referenced field MUST exist in the dependency's actual result structure

Execution Mode Classification:
- NORMAL: Bounded objectives with clear completion. User expects immediate interactive response. Examples: "Check if file exists", "Search web for X", "Analyze these 3 files and report findings", "Convert currency", "Audit project and report findings".
- AUTONOMOUS: Open-ended/iterative objectives requiring persistence, continuation, background execution. User explicitly or implicitly requires continuation until success condition, checkpoint/restart, or background work. Examples: "Fix all issues until tests pass", "Keep working until clean", "Investigate and resolve", "Run overnight and save progress", "Do this in background while I work", "Audit project, fix issues, run tests until everything passes".

Respond with ONLY a JSON object matching this schema:
{{
  "goals": [
    {{"id": "goal_0", "capability_id": "weather.current", "inputs": {{"location": "Patna, Bihar"}}, "depends_on": []}},
    {{"id": "goal_1", "capability_id": "weather.forecast", "inputs": {{"location": "Patna, Bihar"}}, "depends_on": []}},
    {{"id": "goal_2", "capability_id": "currency.convert", "inputs": {{"from": "USD", "to": "INR", "amount": 1}}, "depends_on": []}},
    {{"id": "goal_3", "capability_id": "web.search", "inputs": {{"query": "Jharkhand protest outcome"}}, "depends_on": []}},
    {{"id": "goal_4", "capability_id": "chat.respond", "inputs": {{"message": "Summarize all results: weather, currency, and web search"}}, "depends_on": ["goal_0", "goal_1", "goal_2", "goal_3"]}}
  ],
  "execution_mode": "NORMAL",
  "execution_mode_confidence": 0.95,
  "execution_mode_reasons": ["bounded_objective", "clear_completion_criteria"]
}}

Example with dependency reference:
{{
  "goals": [
    {{"id": "goal_0", "capability_id": "filesystem.search", "inputs": {{"path": "/mnt/dev/languages/python/parika", "pattern": "parika*"}}, "depends_on": []}},
    {{"id": "goal_1", "capability_id": "filesystem.list", "inputs": {{"path": "{{goal_0.result.path}}"}}, "depends_on": ["goal_0"]}},
    {{"id": "goal_2", "capability_id": "chat.respond", "inputs": {{"message": "List the PARIKA project directory"}}, "depends_on": ["goal_0", "goal_1"]}}
  ],
  "execution_mode": "NORMAL",
  "execution_mode_confidence": 0.9,
  "execution_mode_reasons": ["bounded_objective", "clear_completion_criteria"]
}}

Example AUTONOMOUS:
{{
  "goals": [
    {{"id": "goal_0", "capability_id": "coding.analyze", "inputs": {{"path": "."}}, "depends_on": []}},
    {{"id": "goal_1", "capability_id": "coding.execute_task", "inputs": {{"task": "fix all issues"}}, "depends_on": ["goal_0"]}},
    {{"id": "goal_2", "capability_id": "shell.execute", "inputs": {{"command": "pytest"}}, "depends_on": ["goal_1"]}},
    {{"id": "goal_3", "capability_id": "chat.respond", "inputs": {{"message": "Report final status"}}, "depends_on": ["goal_0", "goal_1", "goal_2"]}}
  ],
  "execution_mode": "AUTONOMOUS",
  "execution_mode_confidence": 0.9,
  "execution_mode_reasons": ["explicit_continue_until_criteria", "requires_persistence", "iterative_replanning"]
}}

Capability parameter schemas:
{capability_schemas}

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
    # Execution mode classification from LLM
    proposed_semantic_mode: ExecutionMode = ExecutionMode.NORMAL
    """Semantic execution mode proposed by LLM"""
    execution_mode_confidence: float | None = None
    """Confidence in execution mode classification (0.0-1.0), None if missing"""
    execution_mode_reasons: tuple[str, ...] = ()
    """Structured reasons for execution mode classification"""
    # Forensic: raw LLM-provided fields
    raw_execution_mode: str | None = None
    raw_confidence: Any | None = None
    raw_reasons: Any | None = None


class DecompositionError(Exception):
    """Raised when goal decomposition fails."""
    pass


def _validate_decomposition(
    goals: list[Goal],
    user_message: str,
    capability_registry: CapabilityRegistry,
) -> None:
    """
    Validate that a decomposition meets the universal structural contract.

    A valid decomposition:
    - MUST contain exactly one chat.respond goal
    - chat.respond MUST be the final goal
    - chat.respond MUST depend on ALL preceding goals
    - A simple request with only chat.respond is valid with no dependencies
    """
    if not goals:
        raise DecompositionError("Decomposition produced no goals")

    chat_respond_goals = [
        goal for goal in goals
        if goal.capability_id == "chat.respond"
    ]

    if len(chat_respond_goals) != 1:
        raise DecompositionError(
            "Decomposition must contain exactly one chat.respond goal; "
            f"got {len(chat_respond_goals)}"
        )

    synthesis_goal = chat_respond_goals[0]

    if goals[-1].id != synthesis_goal.id:
        raise DecompositionError(
            f"chat.respond goal {synthesis_goal.id} must be the final goal"
        )

    expected_dependencies = {goal.id for goal in goals[:-1]}
    actual_dependencies = set(synthesis_goal.depends_on)

    missing_dependencies = expected_dependencies - actual_dependencies
    unexpected_dependencies = actual_dependencies - expected_dependencies

    if missing_dependencies or unexpected_dependencies:
        details = []

        if missing_dependencies:
            details.append(
                f"missing dependencies: {sorted(missing_dependencies)}"
            )

        if unexpected_dependencies:
            details.append(
                f"unexpected dependencies: {sorted(unexpected_dependencies)}"
            )

        raise DecompositionError(
            f"Final chat.respond goal {synthesis_goal.id} has invalid dependencies: "
            + "; ".join(details)
        )

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

        # Build capability parameter schemas from the registry's tool affordance metadata
        capability_schemas = _build_capability_schemas(
            self._capability_registry, available_capabilities
        )
        capability_schemas_text = _format_capability_schemas_for_prompt(capability_schemas)

        # Build the decomposition prompt
        system_prompt = _DECOMPOSITION_SYSTEM_PROMPT_TEMPLATE.format(
            capability_schemas=capability_schemas_text,
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

        # Execute decomposition via cloud provider chain with failover
        max_retries_per_provider = 1
        last_exception = None
        attempted_models: set[tuple[str, str]] = set()
        
        while True:
            # Try current provider with retries for transient transport errors
            for attempt in range(max_retries_per_provider + 1):
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
                    attempted_models.add((provider_id, model.id))
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
                    
                    goals, proposed_mode, confidence, reasons, proposed_mode_raw, confidence_raw, reasons_raw = self._parse_decomposition(
                        raw_response, available_capabilities, user_message
                    )
                    
                    # Validate that decomposition meets structural contract
                    _validate_decomposition(goals, user_message, self._capability_registry)
                    
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
                    
                    # FORENSIC: Log admission decision fields
                    if trace_id:
                        log_generic(trace_id, "decomposition.proposed", {
                            "proposed_mode": proposed_mode.value,
                            "confidence": confidence,
                            "reasons": list(reasons),
                        })
                    
                    return DecompositionResult(
                        goals=tuple(goals),
                        raw_response=raw_response,
                        successful_provider_id=provider_id,
                        successful_model_id=model.id,
                        proposed_semantic_mode=proposed_mode,
                        execution_mode_confidence=confidence,
                        execution_mode_reasons=reasons,
                        raw_execution_mode=proposed_mode_raw,
                        raw_confidence=confidence_raw,
                        raw_reasons=reasons_raw,
                    )
                    
                except DecompositionError as ex:
                    # Contract-invalid response from provider - this is a provider failure
                    # for routing purposes. Advance to next provider in cloud chain.
                    last_exception = ex
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"Decomposition validation failed on provider '{provider_id}' "
                        f"model '{model.id}': {ex}. Advancing cloud chain."
                    )
                    break  # Break retry loop to advance provider chain
                    
                except Exception as ex:
                    last_exception = ex
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Decomposition attempt {attempt + 1} failed: {ex}")
                    if trace_id:
                        log_decomposition_provider_failure(
                            trace_id=trace_id,
                            provider_id=provider_id,
                            model_id=model.id,
                            attempt=attempt + 1,
                            exception=ex,
                            response=getattr(ex, "response_body", None),
                            http_status=getattr(ex, "http_status", None),
                        )
                    # Transport/provider-level errors: retry same provider if retries remain
                    if isinstance(ex, (ProviderConnectionError, ProviderTimeoutError,
                                       ProviderRateLimitError, ProviderServerError,
                                       ProviderModelNotFoundError,
                                       ProviderAuthenticationError, ProviderAuthorizationError)):
                        if attempt < max_retries_per_provider:
                            continue
                        # Retries exhausted for this provider - advance cloud chain
                        logger.warning(
                            f"Provider '{provider_id}' failed after retries. "
                            f"Advancing cloud chain."
                        )
                        break
                    # Other unexpected errors: don't retry, advance chain
                    break
            
            # Current provider failed (validation or transport) - advance to next in chain
            fallback = self._next_cloud_routing_model(provider_id, model, routing_config, attempted_models)
            if fallback is not None:
                provider_id, model = fallback
                context_budget = resolve_runtime_context_budget(
                    model.limits, configuration=self._configuration,
                    required_prompt_tokens=estimated_prompt_tokens,
                )
                continue
            
            # No more providers in chain - all failed
            break
        
        # All providers in chain failed
        raise DecompositionError(
            f"Goal decomposition failed after exhausting cloud provider chain: {last_exception}"
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
            
            # Extract execution mode fields from LLM response
            proposed_mode_raw = data.get("execution_mode")
            confidence_raw = data.get("execution_mode_confidence")
            reasons_raw = data.get("execution_mode_reasons")
            
            # Parse execution mode (normalize case for StrEnum)
            proposed_mode = ExecutionMode.NORMAL
            if proposed_mode_raw:
                # Normalize to lowercase for StrEnum comparison
                normalized_mode = proposed_mode_raw.lower() if isinstance(proposed_mode_raw, str) else proposed_mode_raw
                if normalized_mode in ExecutionMode:
                    # Use the enum member, not the raw string
                    proposed_mode = ExecutionMode(normalized_mode)
            
            # Parse confidence
            confidence = None
            if confidence_raw is not None:
                try:
                    confidence = float(confidence_raw)
                except (ValueError, TypeError):
                    confidence = None
            
            # Parse reasons
            reasons = ()
            if reasons_raw and isinstance(reasons_raw, list):
                reasons = tuple(str(r) for r in reasons_raw)
            
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
            
            return goals, proposed_mode, confidence, reasons, proposed_mode_raw, confidence_raw, reasons_raw
        
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
            "cloud_primary_provider=%s cloud_secondary_provider=%s cloud_fallback_provider=%s",
            routing_config.routing_type,
            routing_config.is_fixed,
            routing_config.fixed_model_id,
            routing_config.cloud_primary_provider,
            routing_config.cloud_secondary_provider,
            routing_config.cloud_fallback_provider,
        )

        if routing_config.routing_type == "cloud":
            providers = {p.id: p for p in self._provider_manager.get_all()}
            # Try cloud primary provider first
            if routing_config.cloud_primary_provider and routing_config.cloud_primary_provider in providers:
                provider = providers[routing_config.cloud_primary_provider]
                if provider.models:
                    model = provider.models[0]
                    logger.debug("GoalDecomposer routing branch=cloud primary provider=%s model=%s", provider.id, model.id)
                    return provider.id, model
            # Try cloud secondary provider
            if routing_config.cloud_secondary_provider and routing_config.cloud_secondary_provider in providers:
                provider = providers[routing_config.cloud_secondary_provider]
                if provider.models:
                    model = provider.models[0]
                    logger.debug("GoalDecomposer routing branch=cloud secondary provider=%s model=%s", provider.id, model.id)
                    return provider.id, model
            # Try cloud fallback provider
            if routing_config.cloud_fallback_provider and routing_config.cloud_fallback_provider in providers:
                provider = providers[routing_config.cloud_fallback_provider]
                if provider.models:
                    model = provider.models[0]
                    logger.debug("GoalDecomposer routing branch=cloud fallback provider=%s model=%s", provider.id, model.id)
                    return provider.id, model
            # Try local fixed model as last resort
            if routing_config.fixed_provider_id and routing_config.fixed_model_id and routing_config.fixed_provider_id in providers:
                provider = providers[routing_config.fixed_provider_id]
                for model in provider.models:
                    if model.id == routing_config.fixed_model_id:
                        logger.debug("GoalDecomposer routing branch=cloud local_fixed provider=%s model=%s", provider.id, model.id)
                        return provider.id, model
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

    def _next_cloud_routing_model(
        self,
        current_provider_id,
        current_model,
        routing_config,
        attempted_models: set[tuple[str, str]] | None = None,
    ):
        if routing_config.routing_type != "cloud":
            return None

        if attempted_models is None:
            attempted_models = set()

        targets = []

        # Build the chain: primary -> secondary -> fallback -> local fixed
        chain = [
            routing_config.cloud_primary_provider,
            routing_config.cloud_secondary_provider,
            routing_config.cloud_fallback_provider,
        ]

        # Find current position in the cloud chain
        current_index = -1
        for i, provider_id in enumerate(chain):
            if provider_id and provider_id == current_provider_id:
                current_index = i
                break

        # If the current provider is outside the cloud chain, it means
        # the local fixed fallback has already been reached. Do not restart
        # the cloud chain.
        if current_index == -1:
            return None

        # Add remaining cloud providers after the current provider.
        for provider_id in chain[current_index + 1:]:
            if provider_id:
                targets.append((provider_id, None))

        # Add local fixed model as the final fallback.
        if routing_config.fixed_model_id:
            if routing_config.fixed_provider_id:
                targets.append(
                    (
                        routing_config.fixed_provider_id,
                        routing_config.fixed_model_id,
                    )
                )
            else:
                targets.append(
                    (
                        None,
                        routing_config.fixed_model_id,
                    )
                )

        providers = {
            provider.id: provider
            for provider in self._provider_manager.get_all()
        }

        for provider_id, model_id in targets:
            if provider_id is not None:
                if provider_id not in providers:
                    continue

                provider = providers[provider_id]

                if model_id is None:
                    if not provider.models:
                        continue

                    candidate = provider.models[0]
                else:
                    candidate = next(
                        (
                            model
                            for model in provider.models
                            if model.id == model_id
                        ),
                        None,
                    )

                    if candidate is None:
                        continue

                candidate_key = (provider.id, candidate.id)

                if candidate_key in attempted_models:
                    continue

                if (
                    provider.id == current_provider_id
                    and candidate.id == current_model.id
                ):
                    continue

                return provider.id, candidate

            else:
                # Search all providers for the configured local fixed model.
                for provider in providers.values():
                    for candidate in provider.models:
                        if candidate.id != model_id:
                            continue

                        candidate_key = (provider.id, candidate.id)

                        if candidate_key in attempted_models:
                            continue

                        if (
                            provider.id == current_provider_id
                            and candidate.id == current_model.id
                        ):
                            continue

                        return provider.id, candidate

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
