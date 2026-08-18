"""
PARIKA Agent Specialization

Defines agent specialization types based on actual repository capabilities.
"""

from enum import StrEnum


class AgentSpecialization(StrEnum):
    """
    Agent specializations derived from actual PARIKA repository modules and capabilities.
    
    Each specialization corresponds to a meaningful domain of capabilities
    that benefit from specialized reasoning, model selection, or workflow patterns.
    """

    GENERAL = "general"
    """General conversational agent - handles chat.respond and fallback tasks"""

    CODING = "coding"
    """Software engineering agent - handles coding.execute_task, coding.plan_change"""

    RESEARCH = "research"
    """Information gathering agent - handles web.search, news.*, knowledge capabilities"""

    MEDIA = "media"
    """Media playback/control agent - handles media.* capabilities"""

    SYSTEM = "system"
    """System utilities agent - handles filesystem, shell, currency, weather, expense, runtime"""

    VISION = "vision"
    """Visual/multimedia agent - handles vision, ocr, video, generation capabilities"""