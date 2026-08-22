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
from parika.core.brain.brain_request import BrainRequest
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolution import CapabilityResolution
from parika.core.planner.goal import Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest


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
        brain: Brain,
        capability_registry: CapabilityRegistry,
        provider_manager: ProviderManager,
    ) -> None:
        self._brain = brain
        self._capability_registry = capability_registry
        self._provider_manager = provider_manager

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
        if available_capabilities is None:
            available_capabilities = frozenset(
                cap.id for cap in self._capability_registry.get_all()
                if cap.enabled
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

        # Use the routing model (chat.respond) for decomposition
        def _build_request(
            resolution: CapabilityResolution,
            model: ProviderModel,
        ) -> ProviderRequest:
            return ChatRequest(messages=messages)

        decomposition_goal = Goal(
            id=f"decompose_{uuid4().hex}",
            capability_id="chat.respond",
            inputs={"decomposition_request": user_message},
            provider_request_builder=_build_request,
            metadata={
                "execution_requirements": {
                    "tool_calling": "not_needed",
                    "streaming_required": False,
                }
            },
        )

        # Execute decomposition goal
        response = self._brain.handle(BrainRequest(goals=(decomposition_goal,)))

        if not response.results or not response.results[0].succeeded:
            # Fallback: treat as single chat goal
            return self._fallback_single_goal(user_message)

        raw_response = self._extract_text(response.results[0])
        goals = self._parse_decomposition(raw_response, available_capabilities, user_message)

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


def create_goal_decomposer(
    *,
    brain: Brain,
    capability_registry: CapabilityRegistry,
    provider_manager: ProviderManager,
) -> GoalDecomposer:
    """Factory function to create a GoalDecomposer."""
    return GoalDecomposer(
        brain=brain,
        capability_registry=capability_registry,
        provider_manager=provider_manager,
    )