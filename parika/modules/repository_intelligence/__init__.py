"""
PARIKA Repository Intelligence Module package.

Delivers Workspace Understanding, Repository Understanding, and
Project Indexing as one cohesive Module (see
docs/development/Module_Guide.md sections
5-7).
"""

from __future__ import annotations

from .driver import RepositoryIntelligenceModuleDriver
from .manifest import (
    REPOSITORY_INTELLIGENCE_MODULE_ID,
    REPOSITORY_INTELLIGENCE_MODULE_VERSION,
    create_repository_intelligence_module,
    create_repository_intelligence_module_manifest,
)

__all__ = [
    "REPOSITORY_INTELLIGENCE_MODULE_ID",
    "REPOSITORY_INTELLIGENCE_MODULE_VERSION",
    "RepositoryIntelligenceModuleDriver",
    "create_repository_intelligence_module",
    "create_repository_intelligence_module_manifest",
]
