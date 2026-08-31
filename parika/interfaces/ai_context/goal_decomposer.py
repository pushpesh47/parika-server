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
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from parika.core.brain.brain import Brain
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.planner.goal import Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.planner.model_selection.routing_config import RoutingConfig, load_routing_config
from parika.core.planner.model_selection.routing_strategy import select_fixed_routing_model
from parika.core.planner.model_selection.requirements import ExecutionRequirements, ThinkingMode, Requirement
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.forensic_log import (
    get_current_trace_id,
    log_decomposer_input,
    log_decomposition_raw,
    log_decomposition_goals,
)


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

        # FORENSIC: Log decomposer input
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
                request_options={"reasoning": False},
                reasoning=False,
                num_capabilities=len(capability_ids),
                capability_ids=capability_ids,
                system_prompt=system_prompt,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )

        # Get the routing model for decomposition
        routing_model = self._get_routing_model()
        if routing_model is None:
            # Fallback: treat as single chat goal
            return self._fallback_single_goal(user_message)
        
        # Unpack the tuple
        provider_id, model = routing_model

        # Execute decomposition via direct provider inference
        chat_request = ChatRequest(
            messages=messages,
            options=RequestOptions(reasoning=False),
        )

        try:
            response = self._provider_manager.execute(
                provider_id=provider_id,
                model=model,
                request=chat_request,
            )
        except Exception:
            # Fallback on any provider execution error
            return self._fallback_single_goal(user_message)

        # Extract the response text
        raw_response = self._extract_text_from_provider_response(response)
        
        # FORENSIC: Log raw decomposition output
        if trace_id:
            log_decomposition_raw(
                trace_id=trace_id,
                raw_response=raw_response,
            )

        goals = self._parse_decomposition(raw_response, available_capabilities, user_message)
        
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
        )

    def _parse_decomposition(
        self,
        raw_response: str,
        available_capabilities: frozenset[str],
        user_message: str,
    ) -> list[Goal]:
        """Parse LLM response into Goal objects."""
        try:
            # Try to extract JSON from response - the LLM outputs JSON in a code block
            # Look for ```json ... ``` or just the JSON object
            import re
            
            # First try to find JSON in a code block
            code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_response, re.DOTALL)
            if code_block_match:
                json_str = code_block_match.group(1)
                data = json.loads(json_str)
            else:
                # Fallback: find the last {...} block that parses as JSON
                json_matches = list(re.finditer(r'\{.*?\}', raw_response, re.DOTALL))
                if not json_matches:
                    raise ValueError("No JSON object found in response")
                
                data = None
                for match in reversed(json_matches):
                    try:
                        data = json.loads(match.group())
                        break
                    except json.JSONDecodeError:
                        continue
                
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
            # Fallback on parse failure
            return [self._fallback_single_goal(user_message).goals[0]]

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

    def _fallback_single_goal(self, user_message: str) -> DecompositionResult:
        """Fallback to single chat.respond goal."""
        goal = Goal(
            id=f"fallback_{uuid4().hex}",
            capability_id="chat.respond",
            inputs={"message": user_message},
        )
        return DecompositionResult(
            goals=(goal,),
            raw_response="Fallback to single chat.respond goal",
        )

    def _extract_text(self, goal_result) -> str:
        """Extract text from goal result."""
        if goal_result.response is None:
            return ""
        
        backend_response = goal_result.response.outputs.get("result")
        if hasattr(backend_response, "message"):
            return backend_response.message.content
        return str(backend_response)

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
        """Get the routing model from configuration."""
        # Get routing config
        routing_config = load_routing_config(self._configuration)
        
        if not routing_config.is_fixed:
            # For non-fixed mode, we would need to use the full model selection
            # For now, only support fixed mode as per current config
            return None
        
        # Get all providers
        providers = self._provider_manager.get_all()
        
        # Create minimal execution requirements for routing model
        from parika.core.provider_manager.model_capability import ModelCapability
        requirements = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            tool_calling=Requirement.NOT_NEEDED,
            streaming_required=False,
            required_modalities=frozenset(["text"]),
        )
        
        # Select the fixed routing model
        selection_result = select_fixed_routing_model(
            providers=providers,
            requirements=requirements,
            routing_config=routing_config,
            logger=__import__('logging').getLogger(__name__),
        )
        
        if selection_result is None or selection_result.selected_model is None:
            return None
        
        return (selection_result.selected_provider_id, selection_result.selected_model)


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