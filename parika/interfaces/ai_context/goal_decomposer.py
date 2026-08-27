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
from parika.core.provider_manager.options import RequestOptions
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest


DECOMPOSITION_DOMAIN_KEYWORDS: dict[str, frozenset[str]] = {
    "weather": frozenset({
        "weather", "temperature", "forecast", "rain", "sunny", "cloudy",
        "humidity", "wind", "climate", "storm", "snow", "hot", "cold",
        "degrees", "celsius", "fahrenheit", "precipitation", "conditions"
    }),
    "currency": frozenset({
        "currency", "exchange", "rate", "convert", "usd", "eur", "inr",
        "gbp", "jpy", "cny", "money", "fx", "forex", "dollar", "euro",
        "rupee", "yen", "yuan", "pound", "bitcoin", "crypto", "btc"
    }),
    "web": frozenset({
        "search", "web", "google", "internet", "look up", "find", "query",
        "browse", "lookup", "online", "website", "url", "link"
    }),
    "filesystem": frozenset({
        "file", "read", "write", "list", "directory", "folder", "path",
        "open", "save", "create", "delete", "copy", "move", "mkdir",
        "touch", "cat", "ls", "dir", "folder", "disk", "storage"
    }),
    "shell": frozenset({
        "shell", "command", "execute", "run", "terminal", "bash", "cmd",
        "script", "process", "command line", "cli", "sh", "zsh", "powershell"
    }),
    "vision": frozenset({
        "image", "picture", "photo", "describe", "analyze", "detect",
        "vision", "object", "face", "scene", "visual", "look at", "see",
        "identify", "recognize", "classify", "caption"
    }),
    "video": frozenset({
        "video", "movie", "clip", "generate", "edit", "film", "record",
        "animate", "animation", "footage", "timeline", "frame"
    }),
    "image": frozenset({
        "image", "generate", "create", "picture", "draw", "art", "illustration",
        "generate image", "make image", "create picture", "draw"
    }),
    "ocr": frozenset({
        "ocr", "extract", "text", "scan", "pdf", "document", "read",
        "recognize", "transcribe", "digitize", "read text"
    }),
    "document": frozenset({
        "document", "pdf", "read", "extract", "summarize", "analyze",
        "doc", "docx", "txt", "markdown", "md", "report", "paper",
        "contract", "invoice", "receipt", "form"
    }),
    "memory": frozenset({
        "memory", "remember", "forget", "recall", "store", "note",
        "memorize", "save", "retention", "long term", "permanent"
    }),
    "news": frozenset({
        "news", "latest", "headlines", "current", "today", "breaking",
        "articles", "journalism", "press", "media", "reporters"
    }),
    "expense": frozenset({
        "expense", "spend", "cost", "track", "budget", "log", "record",
        "spent", "paid", "purchase", "buy", "bought", "financial"
    }),
    "media": frozenset({
        "media", "play", "music", "video", "song", "audio", "pause",
        "resume", "stop", "volume", "playlist", "queue", "track"
    }),
    "runtime": frozenset({
        "time", "date", "datetime", "now", "current", "clock", "system",
        "info", "timestamp", "timezone", "utc", "local time", "what time"
    }),
    "coding": frozenset({
        "code", "coding", "program", "function", "class", "refactor",
        "search", "parse", "symbol", "debug", "bug", "fix", "implement",
        "feature", "module", "library", "api", "syntax", "ast"
    }),
    "voice": frozenset({
        "voice", "speech", "speak", "listen", "transcribe", "tts", "stt",
        "audio", "record", "microphone", "speech to text", "text to speech"
    }),
}


def _filter_capabilities_by_domain(
    user_message: str,
    capability_registry: CapabilityRegistry,
) -> frozenset[str]:
    """
    Filter capabilities based on domain keywords in the user message.
    
    If no domain keywords match, returns ALL enabled capabilities (safe fallback).
    Always includes chat.respond for synthesis.
    """
    query_lower = user_message.lower()
    query_words = set(re.findall(r"[a-z0-9]+", query_lower))
    
    # Determine relevant domains
    relevant_domains = set()
    for domain, keywords in DECOMPOSITION_DOMAIN_KEYWORDS.items():
        if query_words & keywords:
            relevant_domains.add(domain)
    
    # If no domains matched, return all capabilities (safe fallback)
    if not relevant_domains:
        all_caps = frozenset(
            cap.id for cap in capability_registry.get_all()
            if cap.enabled
        )
        return all_caps
    
    # Filter capabilities by domain
    # Use first part of capability ID as domain
    all_caps = capability_registry.get_all()
    enabled_caps = [cap for cap in all_caps if cap.enabled]
    
    cap_to_domain = {}
    for cap in enabled_caps:
        domain = cap.id.split(".")[0]
        cap_to_domain[cap.id] = domain
    
    filtered = frozenset(
        cap_id for cap_id, domain in cap_to_domain.items()
        if domain in relevant_domains
    )
    
    # Always include chat.respond for synthesis
    chat_respond_available = any(
        cap.id == "chat.respond" for cap in enabled_caps
    )
    if chat_respond_available:
        filtered = filtered | frozenset(["chat.respond"])
    
    return filtered


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
                                   Defaults to domain-filtered capabilities.
        
        Returns:
            DecompositionResult with goals and raw response
        """
        # Apply deterministic domain filtering if not explicitly provided
        if available_capabilities is None:
            available_capabilities = _filter_capabilities_by_domain(
                user_message, self._capability_registry
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
            return ChatRequest(
                messages=messages,
                options=RequestOptions(reasoning=False),
            )

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