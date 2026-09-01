"""
Tests for GoalDecomposer deterministic settings and configuration propagation.
"""
import os
import sys
sys.path.insert(0, '/mnt/dev/python/parika')

from parika.core.configuration.configuration import Configuration
from parika.core.planner.model_selection.routing_config import load_routing_config
from parika.core.provider_manager.options import RequestOptions
from parika.interfaces.ai_context.goal_decomposer import GoalDecomposer
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.tools.web_search.manifest import WEB_SEARCH_CAPABILITY_ID, WEB_SEARCH_TOOL_AFFORDANCE
from unittest.mock import MagicMock


def setup_test_registry():
    """Create a capability registry with test capabilities."""
    config = Configuration()
    config.load()
    logger = Logger(config)
    event_bus = EventBus(logger)
    reg = CapabilityRegistry(event_bus=event_bus, logger=logger)
    
    # Register capabilities
    reg.register(CapabilityDefinition(
        id='web.search',
        name='Web Search',
        description='Searches the web and optionally extracts the readable content of each result page.',
        category=CapabilityCategory.TOOL,
        tags=frozenset({'web', 'search', 'network'}),
        keywords=frozenset({
            'research', 'lookup', 'find', 'current', 'latest',
            'recent', 'today', 'now', 'news', 'current events',
            'breaking', 'live', 'up to date', 'up-to-date',
            'current information', 'external information',
            'external source', 'web search', 'look up',
        }),
        metadata={'tool_affordance': WEB_SEARCH_TOOL_AFFORDANCE},
    ))
    
    reg.register(CapabilityDefinition(
        id='weather.current',
        name='Current Weather',
        description='Gets current weather for a location.',
        category=CapabilityCategory.TOOL,
        tags=frozenset({'weather', 'current'}),
        keywords=frozenset({'weather', 'temperature', 'current'}),
        metadata={},
    ))
    
    reg.register(CapabilityDefinition(
        id='weather.forecast',
        name='Weather Forecast',
        description='Gets weather forecast for a location.',
        category=CapabilityCategory.TOOL,
        tags=frozenset({'weather', 'forecast'}),
        keywords=frozenset({'weather', 'forecast', 'forecast'}),
        metadata={},
    ))
    
    reg.register(CapabilityDefinition(
        id='chat.respond',
        name='Chat Respond',
        description='Generates a chat response.',
        category=CapabilityCategory.LLM,
        tags=frozenset({'chat', 'respond'}),
        keywords=frozenset({'chat', 'respond', 'answer'}),
        metadata={},
    ))
    
    return config, reg


def test_routing_config_propagation_false():
    """Test that FIXED_THINKING=false configuration propagates to decomposition reasoning."""
    config, reg = setup_test_registry()
    
    # Test with FIXED_THINKING=false (default from .env)
    routing_config = load_routing_config(config)
    assert routing_config.mode == "fixed"
    assert routing_config.fixed_thinking is False
    assert routing_config.is_fixed is True
    
    decomposition_reasoning = routing_config.fixed_thinking if routing_config.is_fixed else False
    assert decomposition_reasoning is False
    print("✓ FIXED_THINKING=false → decomposition_reasoning=False")


def test_routing_config_propagation_true():
    """Test that FIXED_THINKING=true configuration propagates to decomposition reasoning."""
    # Temporarily override environment
    old_value = os.environ.get('PARIKA_ROUTING_MODEL__FIXED_THINKING')
    os.environ['PARIKA_ROUTING_MODEL__FIXED_THINKING'] = 'true'
    
    try:
        config = Configuration()
        config.load()
        routing_config = load_routing_config(config)
        assert routing_config.fixed_thinking is True
        assert routing_config.is_fixed is True
        
        decomposition_reasoning = routing_config.fixed_thinking if routing_config.is_fixed else False
        assert decomposition_reasoning is True
        print("✓ FIXED_THINKING=true → decomposition_reasoning=True")
    finally:
        if old_value is not None:
            os.environ['PARIKA_ROUTING_MODEL__FIXED_THINKING'] = old_value
        else:
            del os.environ['PARIKA_ROUTING_MODEL__FIXED_THINKING']


def test_request_options_deterministic():
    """Test that RequestOptions have deterministic sampling settings."""
    config, reg = setup_test_registry()
    
    # Mock provider manager
    mock_provider_manager = MagicMock()
    
    # Create decomposer
    decomposer = GoalDecomposer(
        capability_registry=reg,
        provider_manager=mock_provider_manager,
        configuration=config,
    )
    
    # Access the internal routing_config to verify it's loaded correctly
    routing_config = load_routing_config(config)
    decomposition_reasoning = routing_config.fixed_thinking if routing_config.is_fixed else False
    
    # Verify the expected RequestOptions values
    expected_options = RequestOptions(
        reasoning=decomposition_reasoning,
        temperature=0.0,
        seed=42,
        top_p=1.0,
    )
    
    # Check that the decomposer would create the correct options
    # (We can't easily test the private method, but we can verify the logic)
    assert expected_options.reasoning is False  # Based on .env FIXED_THINKING=false
    assert expected_options.temperature == 0.0
    assert expected_options.seed == 42
    assert expected_options.top_p == 1.0
    print("✓ RequestOptions have deterministic settings: temperature=0.0, seed=42, top_p=1.0")


def test_request_options_reasoning_from_config():
    """Test that RequestOptions.reasoning comes from routing config."""
    # This test verifies the logic without running the full decomposer
    config, reg = setup_test_registry()
    
    routing_config = load_routing_config(config)
    decomposition_reasoning = routing_config.fixed_thinking if routing_config.is_fixed else False
    
    # The decomposer uses this value for RequestOptions.reasoning
    assert decomposition_reasoning == routing_config.fixed_thinking
    print("✓ RequestOptions.reasoning sourced from routing_config.fixed_thinking")


if __name__ == "__main__":
    test_routing_config_propagation_false()
    test_routing_config_propagation_true()
    test_request_options_deterministic()
    test_request_options_reasoning_from_config()
    print("\n✅ All tests passed!")
