"""
PARIKA Autonomous Execution - ExecutionRequirements Serialization

Provides serialization/deserialization of ExecutionRequirements for
autonomous task persistence. Handles enum coercion, frozenset conversion,
and ResourceSnapshot exclusion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from types import MappingProxyType
from typing import Any, get_type_hints

from parika.core.planner.model_selection.requirements import (
    ExecutionRequirements,
    ReasoningLevel,
    LatencyPreference,
    Requirement,
    CreativityLevel,
    AccuracyPreference,
    CostPreference,
    DeploymentPreference,
    ExecutionPriority,
    ImportanceLevel,
    InformationFreshness,
    CapabilityHint,
    ModelCapability,
    ModelExecutionFeature,
)
from parika.core.provider_manager.model_capability import ModelCapability as ProviderModelCapability
from parika.core.provider_manager.model_execution_feature import ModelExecutionFeature as ProviderModelExecutionFeature


# Field type mappings for serialization/deserialization
_ENUM_FIELD_TYPES: dict[str, type] = {
    "capability": ModelCapability,
    "reasoning_level": ReasoningLevel,
    "latency_preference": LatencyPreference,
    "tool_calling": Requirement,
    "vision": Requirement,
    "structured_output": Requirement,
    "creativity": CreativityLevel,
    "memory_importance": ImportanceLevel,
    "accuracy_preference": AccuracyPreference,
    "cost_preference": CostPreference,
    "deployment_preference": DeploymentPreference,
    "execution_priority": ExecutionPriority,
    "information_freshness": InformationFreshness,
}

_FROZENSET_STR_FIELDS = (
    "required_specializations",
    "required_modalities",
    "capability_hints",
)

_FROZENSET_ENUM_FIELD_TYPES: dict[str, type] = {
    "required_capabilities": ModelCapability,
    "required_execution_features": ModelExecutionFeature,
}

_PLAIN_FIELDS = (
    "streaming_required",
    "min_context_window",
    "task_category",
    "capability_id",
)

_NESTED_OBJECT_FIELDS = (
    "available_resources",
    "metadata",
)


def serialize_execution_requirements(req: ExecutionRequirements) -> dict[str, Any]:
    """
    Serialize ExecutionRequirements to a JSON-safe dict.
    
    Excludes available_resources (ResourceSnapshot) as it's reconstructed
    at execution time from ResourceManager.
    """
    result = {}
    
    for field in fields(req):
        name = field.name
        value = getattr(req, name)
        
        # Skip available_resources - reconstructed at execution time
        if name == "available_resources":
            continue
            
        # Serialize enums to their string values
        if name in _ENUM_FIELD_TYPES and value is not None:
            result[name] = value.value
        # Serialize frozenset[str] to list
        elif name in _FROZENSET_STR_FIELDS and value:
            result[name] = [str(item) for item in value]
        # Serialize frozenset[Enum] to list of string values
        elif name in _FROZENSET_ENUM_FIELD_TYPES and value:
            enum_type = _FROZENSET_ENUM_FIELD_TYPES[name]
            result[name] = [item.value for item in value]
        # Serialize metadata MappingProxyType to dict
        elif name == "metadata" and value:
            result[name] = dict(value)
        # Plain fields
        elif value is not None:
            result[name] = value
    
    return result


def deserialize_execution_requirements(data: Mapping[str, Any]) -> ExecutionRequirements:
    """
    Deserialize ExecutionRequirements from a JSON-safe dict.
    
    The available_resources field will be None and must be populated
    at execution time from ResourceManager.
    """
    # Build kwargs for ExecutionRequirements constructor
    kwargs = {}
    
    for field in fields(ExecutionRequirements):
        name = field.name
        
        # Skip available_resources - will be set at execution time
        if name == "available_resources":
            continue
            
        if name not in data:
            continue
            
        value = data[name]
        
        if value is None:
            continue
            
        # Convert enum strings to enum values
        if name in _ENUM_FIELD_TYPES:
            enum_type = _ENUM_FIELD_TYPES[name]
            kwargs[name] = enum_type(value)
        # Convert frozenset[str] from list
        elif name in _FROZENSET_STR_FIELDS:
            if isinstance(value, (list, tuple, set, frozenset)):
                kwargs[name] = frozenset(str(item) for item in value)
            else:
                kwargs[name] = frozenset()
        # Convert frozenset[Enum] from list
        elif name in _FROZENSET_ENUM_FIELD_TYPES:
            enum_type = _FROZENSET_ENUM_FIELD_TYPES[name]
            if isinstance(value, (list, tuple, set, frozenset)):
                kwargs[name] = frozenset(enum_type(item) for item in value)
            else:
                kwargs[name] = frozenset()
        # Convert metadata to MappingProxyType
        elif name == "metadata":
            if isinstance(value, Mapping):
                kwargs[name] = MappingProxyType(dict(value))
            else:
                kwargs[name] = MappingProxyType({})
        # Plain fields
        else:
            kwargs[name] = value
    
    # Ensure capability is provided (required field)
    if "capability" not in kwargs:
        raise ValueError("capability is required for ExecutionRequirements")
    
    return ExecutionRequirements(**kwargs)


def serialize_for_persistence(req: ExecutionRequirements) -> dict[str, Any]:
    """
    Serialize ExecutionRequirements for database persistence.
    
    This is an alias for serialize_execution_requirements that makes
    the intent clear for database storage.
    """
    return serialize_execution_requirements(req)


def deserialize_from_persistence(data: dict[str, Any]) -> ExecutionRequirements:
    """
    Deserialize ExecutionRequirements from database storage.
    
    This is an alias for deserialize_execution_requirements that makes
    the intent clear for database loading.
    """
    return deserialize_execution_requirements(data)