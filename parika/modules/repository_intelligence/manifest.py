"""
PARIKA Repository Intelligence Module - Manifest

Defines the static ModuleManifest describing the Repository
Intelligence Module -- Workspace Understanding, Repository
Understanding, and Project Indexing, delivered as one cohesive Module
per
docs/development/Module_Guide.md section
5.2.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import RepositoryIntelligenceModuleDriver

REPOSITORY_INTELLIGENCE_MODULE_ID = "repository_intelligence"
REPOSITORY_INTELLIGENCE_MODULE_VERSION = "1.0.0"


def create_repository_intelligence_module_manifest() -> ModuleManifest:
    return ModuleManifest(
        id=REPOSITORY_INTELLIGENCE_MODULE_ID,
        name="Repository Intelligence",
        version=REPOSITORY_INTELLIGENCE_MODULE_VERSION,
        description=(
            "Registers the RepositoryKnowledgeEngine with "
            "KnowledgeManager for the already-existing REPOSITORY/"
            "WORKSPACE source kinds: workspace/repository/project "
            "discovery, read-only Git metadata, README understanding, "
            "and Project Awareness (framework/package manager/build "
            "system/test framework/linter/formatter detection)."
        ),
        author="PARIKA",
        license="MIT",
        tags=("repository", "workspace", "indexing"),
        driver=(
            "parika.modules.repository_intelligence.driver."
            "RepositoryIntelligenceModuleDriver"
        ),
    )


def create_repository_intelligence_module(
    driver: RepositoryIntelligenceModuleDriver,
) -> Module:
    return Module(
        id=REPOSITORY_INTELLIGENCE_MODULE_ID,
        manifest=create_repository_intelligence_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
