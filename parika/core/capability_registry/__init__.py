"""
PARIKA Capability Registry.

Provides the central registry for capability definitions within PARIKA.
"""

from .capability_category import CapabilityCategory
from .capability_definition import CapabilityDefinition
from .capability_registry import CapabilityRegistry

__all__ = [
    "CapabilityCategory",
    "CapabilityDefinition",
    "CapabilityRegistry",
]