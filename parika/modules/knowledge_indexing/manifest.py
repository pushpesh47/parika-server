"""
PARIKA Knowledge Indexing Module - Manifest

Defines the static ModuleManifest describing the Knowledge Indexing
Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import KnowledgeIndexingModuleDriver

KNOWLEDGE_INDEXING_MODULE_ID = "knowledge_indexing"
KNOWLEDGE_INDEXING_MODULE_VERSION = "1.0.0"


def create_knowledge_indexing_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Knowledge Indexing
    Module.
    """

    return ModuleManifest(
        id=KNOWLEDGE_INDEXING_MODULE_ID,
        name="Knowledge Indexing",
        version=KNOWLEDGE_INDEXING_MODULE_VERSION,
        description=(
            "Registers the built-in Document and Code KnowledgeEngine "
            "implementations with KnowledgeManager: stdlib-only "
            "paragraph-based document indexing and ast-based Python "
            "symbol/import indexing."
        ),
        author="PARIKA",
        license="MIT",
        tags=("knowledge", "indexing", "search"),
        driver=(
            "parika.modules.knowledge_indexing.driver."
            "KnowledgeIndexingModuleDriver"
        ),
    )


def create_knowledge_indexing_module(
    driver: KnowledgeIndexingModuleDriver,
) -> Module:
    """
    Build the immutable Module descriptor for the Knowledge Indexing
    Module.
    """

    return Module(
        id=KNOWLEDGE_INDEXING_MODULE_ID,
        manifest=create_knowledge_indexing_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
